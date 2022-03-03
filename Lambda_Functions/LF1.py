import math
import dateutil.parser
import datetime
import time
import os
import logging
import re
import boto3
import json
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
table = dynamodb.Table('restaurantSuggestionStore')

def elicit_slot(session_attributes, intent_name, slots, slot_to_elicit, message):
    return {
        'sessionAttributes': session_attributes,
        'dialogAction': {
            'type': 'ElicitSlot',
            'intentName': intent_name,
            'slots': slots,
            'slotToElicit': slot_to_elicit,
            'message': message
        }
    }
    
def handle_greeting_intent(event):
    response = table.query(KeyConditionExpression=Key('identity').eq(1))
    data = response['Items'][0]
    suggestions = data['suggestions']
    status = data['isFirstTime']
   
    if not status:
        # compose message to return
        return {
            'dialogAction': {
                "type": "ElicitIntent",
                'message': {
                    'contentType': 'PlainText',
                    'content': 'Hi there, how can I help?'}
            }
        }
        
    else:
        return {
            'dialogAction': {
                "type": "ElicitIntent",
                'message': {
                    'contentType': 'PlainText',
                    'content': 'Welcome back! Here are your previous suggestions! ' + suggestions}
            }
        }

def close(session_attributes, fulfillment_state, message):
    response = {
        'sessionAttributes': session_attributes,
        'dialogAction': {
            'type': 'Close',
            'fulfillmentState': fulfillment_state,
            'message': message
        }
    }
    return response
    
def handle_thankyou_intent(event):
    # compose message to return
    return {
        'dialogAction': {
            "type": "ElicitIntent",
            'message': {
                'contentType': 'PlainText',
                'content': 'You are welcome!'}
        }
    }
    
def isvalid_date(date):
    try:
        dateutil.parser.parse(date)
        return True
    except ValueError:
        return False

def build_validation_result(is_valid, violated_slot, message_content):
    if message_content is None:
        return {
            "isValid": is_valid,
            "violatedSlot": violated_slot,
        }

    return {
        'isValid': is_valid,
        'violatedSlot': violated_slot,
        'message': {'contentType': 'PlainText', 'content': message_content}
    }
    
def parse_int(n):
    try:
        return int(n)
    except ValueError:
        return float('nan')
        
def isvalid_email(email):
    regex = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    if(re.fullmatch(regex, email)):
        return True
    else:
        return False
        
def validate_dining_suggestion(cuisine, noofPeople, date, time, location, email):
    
    cuisines = ['indian', 'italian', 'chinese', 'vietnamese', 'mexican',
                'french', 'thai', 'burmese', 'japanese', 'persian', 'turkish']

    if cuisine is not None and cuisine.lower() not in cuisines:
        return build_validation_result(False,
                                       'Cuisine',
                                       'We do not have that cuisine, can you please try another?')

    if noofPeople is not None:
        noofPeople = int(noofPeople)
        if noofPeople > 20:
            return build_validation_result(False,
                                           'NoofPeople',
                                           'Only a maximum 20 people are allowed to dine, please try again.')
        elif noofPeople < 0:
            return build_validation_result(False,
                                           'NoofPeople',
                                           'There cannot be less than zero people dining, please try again.')

    if date is not None:
        check1=datetime.datetime.strptime(date, '%Y-%m-%d').date()
        check2=datetime.date.today()
        print('#############check1', check1)
        print('#############check2', check2)
        if (isvalid_date(date) == False):
            return build_validation_result(False,
                                           'Date',
                                           'I did not understand that, what date would you like to go dining?')
        elif datetime.datetime.strptime(date, '%Y-%m-%d').date() <= datetime.date.today():
            return build_validation_result(False, 'Date', 'You cannot choose a date from the past, please try again.')

    if time is not None:
        if len(time) != 5:
            return build_validation_result(False, 'Time', 'Not a valid time, please try again.')

        hour, minute = time.split(':')
        hour = parse_int(hour)
        minute = parse_int(minute)
        if math.isnan(hour) or math.isnan(minute):
            return build_validation_result(False, 'Time', 'Not a valid time, please try again.')

        if hour < 10 or hour > 22:
            return build_validation_result(False, 'Time', 'Valid booking hours are from 10am to 10pm, please specify a time in this interval.')

    if location is not None:
        if len(location) < 1:
            return build_validation_result(False, 'Location', 'Not a valid location, please try again.')

    if email is not None:
        if (isvalid_email(email) == False):
            return build_validation_result(False,
                                           'Email',
                                           'This was not a valid email, please try again.')

    return build_validation_result(True, None, None)


def get_slots(intent_request):
    return intent_request['currentIntent']['slots']
   
def delegate(session_attributes, slots):
    return {
        'sessionAttributes': session_attributes,
        'dialogAction': {
            'type': 'Delegate',
            'slots': slots
        }
    }
    
def handle_dining_suggestion_intent(event):
    invocation_source = event['invocationSource']

    slots = get_slots(event)
    location = slots["Location"]
    cuisine = slots["Cuisine"]
    noofPeople = slots["NoofPeople"]
    time = slots["Time"]
    date = slots["Date"]
    phoneNumber = slots["PhoneNumber"]
    email = slots["Email"]
    
    if invocation_source == 'DialogCodeHook':
        validation_result = validate_dining_suggestion(
            cuisine, noofPeople, date, time, location, email)
        if validation_result['isValid'] == False:
            slots[validation_result['violatedSlot']] = None
            return elicit_slot(event['sessionAttributes'],
                               event['currentIntent']['name'],
                               slots,
                               validation_result['violatedSlot'],
                               validation_result['message'])
        else:
            if event['sessionAttributes'] is not None:
                output_session_attributes = event['sessionAttributes']
            else:
                output_session_attributes = {}
            return delegate(output_session_attributes, get_slots(event))
    
    if invocation_source == 'FulfillmentCodeHook':
        if event['sessionAttributes'] is not None:
            output_session_attributes = event['sessionAttributes']
        else:
            output_session_attributes = {}
        queue_message = {"cuisine": cuisine, "email": email, "location": location,
             "noofPeople": noofPeople, "date": date, "time": time}
        print('sending queue_message:',queue_message)
        sqs = boto3.resource('sqs')
        queue = sqs.get_queue_by_name(QueueName='restaurantRequests')
        response = queue.send_message(MessageBody=json.dumps(queue_message))
    return close(event['sessionAttributes'],
        'Fulfilled',
        {'contentType': 'PlainText',
        'content': 'Great! You will receive your suggestion shortly.'})
    
    #queue_message = {"cuisine": cuisine, "phoneNumber": phoneNumber, "email": email, "location": location,
    #                 "noofPeople": noofPeople, "date": date, "time": time}
    #sqs = boto3.client('sqs',endpoint_url="https://sqs.us-east-1.amazonaws.com")
    #response = sqs.send_message(
    #    QueueUrl="https://sqs.us-east-1.amazonaws.com/644169909224/restaurantRequests",
    #    MessageBody=json.dumps(queue_message))
    #print("checking after:",response)
    #print(queue_message)
    #return close(event['sessionAttributes'],
    #             'Fulfilled',
    #             {'contentType': 'PlainText',
    #              'content': 'You’re all set. Expect my suggestions shortly! Have a good day.'})

# lambda handler and dispatching intent funtions

# function to handle the different intents


def dispatch(event):

    logger.debug(
        'dispatch userId={}, intentName={}'.format(event['userId'], event['currentIntent']['name']))

    intent_type = event['currentIntent']['name']

    if (intent_type == 'GreetingIntent'):
        return handle_greeting_intent(event)
    elif(intent_type == 'ThankYouIntent'):
        return handle_thankyou_intent(event)
    elif(intent_type == 'DiningSuggestionsIntent'):
        return handle_dining_suggestion_intent(event)

    raise Exception('Intent with name ' + intent_type + ' not supported')

def lambda_handler(event, context):
    
    os.environ['TZ'] = 'America/New_York'
    time.tzset()
    logger.debug('event.bot.name={}'.format(event['bot']['name']))

    return dispatch(event)
