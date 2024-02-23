import openai
import nltk
import re
import random
import pickle

def get_topics(path_to_topics):

    with open(path_to_topics, "r") as r:
        data = r.read()

    topics = data.strip().split(TOPIC_SPLITTER)
    topics = [topic.strip() for topic in topics if len(topic.strip())>0]

    return topics

def run_gpt4(conversation_Log):
    response = openai.ChatCompletion.create(
        model=model_id,
        messages=conversation_Log
    )

    return response.choices[0].message.role, response.choices[0].message.content.strip()

def pre_process_res(response_text):
    if response_text.startswith("Text:"):
        response_text = response_text.lstrip("Text:")

    response_text = response_text.strip()
    response_text = response_text.rstrip(",.;:?!\"\'")
    response_text = response_text.lstrip(",.;:?!\"\'")

    return response_text

def get_grounded_answers(answer_text, section_text):
    sentences = nltk.sent_tokenize(answer_text)
    curr_sent = sentences[0]
    answers_all = []

    for i in range(1, len(sentences)):
        x_1 = (curr_sent.strip() + " " + sentences[i].strip())
        if (x_1 in section_text):
            curr_sent = x_1
        else:
            answers_all.append(curr_sent)
            curr_sent = sentences[i]

    if not (curr_sent in answers_all):
        answers_all.append(curr_sent)

    return answers_all

def check_overlap(answer_text, section_text):
    length = len(answer_text.split())
    tmp = answer_text
    for i in range(0, int(length/2)):
        tmp = tmp.split(' ', 1)[1]
        if tmp.lower() in section_text.lower():
            return True, tmp
    return False, None

def check_teacher_response(response, topic_background, section):
    response = pre_process_res(response)

    # condition 0
    if (response in cannot_find_text) or (cannot_find_text in response) or ("the text does not" in response):
        print("Condition 0")
        return True, [cannot_find_text]

    # condition 1
    res, tmp_text = check_overlap(response, section)
    if res:
        print("Condition 1")
        return True, [tmp_text]

    # condition 2
    clean_section = re.sub("([\(\[]).*?([\)\]])", "\g<1>\g<2>", section)
    clean_section = ' '.join(clean_section.split())

    res, tmp_text = check_overlap(response, clean_section)
    if res:
        print("Condition 2")
        return True, [tmp_text]

    # condition 3
    sentencess = get_grounded_answers(response, section)

    answer_spans = []

    for sent in sentencess:
        if len(sent) > 0:
            sent_clean = pre_process_res(sent)
            res, tmp_text = check_overlap(sent_clean, section)
            if res:
                answer_spans.append(tmp_text)

    if len(answer_spans) > 0:
        print("Condition 3")
        return True, answer_spans

    # condition 5
    if response in topic_background:
        print("Condition 4")
        return False, [prompt_answer_from_text]

    return False, [prompt_copy_exact_segment]

def teacher_process_one_question(index, doc_info, question):

    title, background, header, section = doc_info

    if index == 0:
        prompt_input = first_prompt_teacher.format(title=title, background=background, instruction_teacher= instruction_teacher, header=header, section=section, question=question)

    else:
        prompt_input = prompt_answer_short.format(question=question)

    teacher_conversations.append({'role': 'user', 'content': prompt_input})

    for i in range(0, TEACHER_PATIENCE):
        role, content = run_gpt4(teacher_conversations)
        teacher_conversations.append({'role': role, 'content': content})
        res, res_prompt = check_teacher_response(content, doc_info[1], doc_info[3])

        if res == True:
            gpt_4_answer = res_prompt
            break

        elif i < 3:
            # ask the given prompt
            teacher_conversations.append({'role': 'user', 'content': res_prompt[0]})

        elif i == 3:
            gpt_4_answer = ["I cannot find the answer. " + content]
            print("final answer didn't match!")

    return gpt_4_answer

def check_question(question):
    if "\n" in question or len(question.split()) > MAX_QUES_LENGTH:
        return False
    return True

def simulate_student(first_question, title, background, header, prev_answer, prompt_arr_student):

    if first_question:
        prompt = student_prompt.format(instruction=student_instruction, title=title, background=background, header=header)

    elif prev_answer == cannot_find_text:
        prompt = random.choice(prompt_arr_student)
        print("Student selected prompt: ", prompt)
        if prompt == interesting_prompt:
            prompt_arr_student.remove(interesting_prompt)

    else:
        prompt = student_prompt_regular

    answer_with_prompt = prev_answer + " " + prompt
    student_conversations.append({'role': 'user', 'content': answer_with_prompt})
    role, new_question = run_gpt4(student_conversations)

    while not check_question(new_question):
        role, new_question = run_gpt4(student_conversations)
        prompt_2 = answer_with_prompt + " Please only ask one short question."
        student_conversations[-1] = {'role': 'user', 'content': prompt_2}

    student_conversations.append({'role': role, 'content': new_question})


    if prompt == interesting_prompt:
        new_question = new_question + " (tell me maximum number of two segments)"

    return new_question

def student_teacher_simulation(doc_info):
    output_res = {}

    prompt_arr_student = [wh_prompt, interesting_prompt, general_prompt, change_aspect]
    title, background, header, section = doc_info

    output_res['title'] = title
    output_res['background'] = background
    output_res['header'] = header
    output_res['section'] = section
    output_res['conversation'] = []


    question = simulate_student(True, title, background, header, "", prompt_arr_student)
    answer_arr = teacher_process_one_question(0, doc_info, question)
    tmp= {'question': question,
          'answer':answer_arr}
    output_res['conversation'].append(tmp)
    answer = ' '.join(answer_arr)

    for i in range(1, CONV_LENGTH):
        question = simulate_student(False, title, background, header, answer, prompt_arr_student)
        answer_arr = teacher_process_one_question(i, doc_info, question)
        tmp = {'question': question,
               'answer': answer_arr}
        output_res['conversation'].append(tmp)
        answer = ' '.join(answer_arr)

    return output_res


prompt_answer_from_text = "Please answer from the given section not the given background description."
prompt_copy_exact_segment = "Please copy the exact segment from the text."
cannot_find_text = "I cannot find the answer."
prompt_answer_short = "{question}\n(Remember that you should select the shortest possible span from the text)."
student_prompt = "{instruction}\nBackground:\n:{title}\n{background}\nHeader: {header}\nPlease start asking questions about: {header}."

student_instruction = """In this task, I am a teacher and have a document, you are a curious student who wants to explore this document by asking questions.
The main objective is to learn most of the document that I have. I will give you background knowledge of the document and the title of the document.
You should ask questions about this title one by one. When you ask a question, I give you the answer, and then you ask your next question.
I’m only allowed to find the answer to your questions from this document, so if I cannot find the answer, I will say “I cannot find the answer, please ask your next question”.
You shouldn’t ask questions that can be answered from my previous answers to your previous questions. You should sometimes ask follow-up questions from my previous answers."""

general_prompt = "Please ask a general question and don't ask a too specific question."
wh_prompt = "Please ask a question starting with where, when, or who."
interesting_prompt = "Please ask what is interesting about this document."
change_aspect = "Please ask a question about another aspect of the topic."
student_prompt_regular = ". Please ask your next question."
prompt_without_ellipsis = "Please repeat your last question by using Ellipsis and co-references."

API_key = ""
openai.api_key = API_key
model_id = "gpt-4"
path_to_topics = "./data_for_simulation.txt"
result_path = './simulated_conversations'
TOPIC_SPLITTER = "<Topic: --------------------------->"

TEACHER_PATIENCE = 4
MAX_QUES_LENGTH = 25
CONV_LENGTH = 12

instruction_teacher = """In this task, you will be given a text about the topic explained above. You will answer my questions from this text.  Please remember that you cannot generate the answer on your own but should only copy a continuous span from the original text and the copied answer should not exceed 40 tokens.  If you cannot find the answer in the text, please generate ‘I cannot find the answer’."""
first_prompt_teacher = "Topic: {title}\n{background}\n{instruction_teacher}\nText:\n{header}\n{section}\nQuestion: {question}"

topics = get_topics(path_to_topics)

simulated_convs = []

for i in range(0, len(topics)):
    teacher_conversations = []
    student_conversations = []
    doc_info = topics[i].strip().split("\n")
    doc_info[3] = ' '.join(doc_info[3].split()).rstrip("CANNOTANSWER").strip()
    doc_info[1] = ' '.join(doc_info[1].split())
    output_res = student_teacher_simulation(doc_info)
    simulated_convs.append(output_res)


with open(result_path, 'wb') as f:
    pickle.dump(simulated_convs)

