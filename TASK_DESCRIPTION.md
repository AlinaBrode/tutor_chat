# Main goal

* create a chat application
* a user chats with LLM
* LLM acts as a tutor

# Technical details

* backend part - python
* frontend part - html, css, js
* configuration file in json
  * prompt
  * credentials
* store conversation in log file
  * prompt should be stored with conversation
* it should be possible to include images into a conversation
  * at the beginning of conversation it should be possible to upload a picture with task description
  * at the beginning of conversation it should be possible to upload a picture with a solution of the task from our student

# Program interface

* a big window with messages from a user and from the system
* smaller window in which a user can input their message
* button "send" on the right side of the smaller window
* message from user is sent either when "send" button is pressed or when "Enter" button is hit
* button "start a new dialog"
* configuration file editor
  * one can edit tutor's prompt
  * credentials for the model
* we are to have in interface some way to show and hide configuration file editor, we don't need it all the time  

# User story, typical interaction with the program

* a user starts the program
* a user presses the button "start a new dialog"
  * new entry for this dialog appears in a log file
  * this entry contains our current prompt for the tutor
* if she wants, user enters images with task description and their solution
* turn-by-turn conversation starts
* conversation is stored in log file

# Model

* Google Gemini
* in config we are to store exact name of model to use and credentials

# Prompt details

* the prompt is a jinja template in which the following variables can be substituted:
  * task - a task to explain (optional text field)
  * task_image - image for task (optional)
  * solution_image - image from a student (optional)
  * dialogue_turns - a text in which turns are marked as "Учитель" and "Ученик"


An example of prompt template:
```
You are a smart teacher who uses socratic method to explain tasks to your student.

Keep conversation with your student in russian.

Optional task to explain: {{task}}
Optional picture for the task: {{task_image}}
Optional solution from a student: {{solution_image}}

Dialogue so far:
{{dialogue_turns}}

Your task is to come up with the next message to a student.

```

# List of models
* on the application start query Google for the list of available models
* in "configuration" page provide a list of available models to user to select from


# Home task estimation

## Placement
* one more button: "Estimate"
* opens/closes panel with student's work estimation
* parameters to set
  * task description (optional)
  * task description image (optional)
  * student's work (optional)
  * student's work image (optional)
* button "Estimate"
* fields to show result:
  * model's estimation (1-5) points
  * model's feedback


## Logic of work
* takes jinja template for student's work estimation
* substitutes variables in the template
* sends prompt to LLM
* get's LLM reaction
  * parse model's reaction, extract next word after "score", place it into "score" field
  * the whole model's response put into "estimation" field of the form
  * make log entry for work estimation on the same level as dialog 


# Conversation export

## Placement
* add a button "Export conversations" alongside the existing controls
* clicking the button opens a side panel similar to the settings or estimation panel

## Functionality
* request the list of stored conversations (id, creation timestamp, first user message)
* allow the user to pick a conversation from a dropdown list
* render a preview that shows the prompt and all turns as "Teacher" / "Student" lines
* provide a "Download conversation" button that saves the rendered text as a plain-text file
