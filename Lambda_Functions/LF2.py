import boto3
import json
import random
from boto3.dynamodb.conditions import Key
import requests
from requests_aws4auth import AWS4Auth
from datetime import datetime

# get credentials to authenticate Elastic search
credentials = boto3.Session().get_credentials()
authent = AWS4Auth(credentials.access_key, credentials.secret_key, 'us-east-1', 'es', session_token=credentials.token)


# connect to the dynamoDB table
dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
table = dynamodb.Table('yelp-restaurants')
table2 = dynamodb.Table('restaurantSuggestionStore')

# function to generate the suggestions message
def generate_suggestions(randomIds, cuisine, queue_message):
    restaurantIds = []
    dynamoDBResponses = []
    for id in randomIds:
        # get elastic search results for the random restaurant
        url2 = 'https://search-restaurant-gkgknrtvkb4drescojoawsqwnm.us-east-1.es.amazonaws.com/restaurants/_search?from=' + str(id) + '&&size=1&&q=cuisine:' + cuisine
        random_elastic_response = requests.get(url2, auth = authent, headers={"Content-Type": "application/json"}).json()
        restaurantIds.append(random_elastic_response['hits']['hits'][0]['_source']['Business ID'])

    for restaurant in restaurantIds:
        # use the elastic ID to get full details from dynamoDb
        dynamoDBResponses.append(table.query(KeyConditionExpression=Key('Business ID').eq(restaurant)))

    output = format_response(dynamoDBResponses, queue_message)

    return output

# function to handle the response
def format_response(responses, message):
    restaurantSuggestions=''
    # get required details
    cuisine = message['cuisine']
    numberOfPeople = message['noofPeople']
    time = message['time']
    date = message['date']

    # make suggestion for each item from dyanmoDB
    for index, item in enumerate(responses):
        data = item['Items'][0]
        restaurant_name = data['Name']
        restaurant_address = data['Address']
        restaurant_rating = data['Rating']
        restaurant_noofreviews = data['Number of Reviews']
        suggestion = '{}.{}, located at {}, Rating : {}, No. of Reviews : {} '.format(index +1, restaurant_name, restaurant_address, restaurant_rating, restaurant_noofreviews)
        restaurantSuggestions += suggestion+'\n'

    # make the message
    reply = 'Hello! \nHere are my {} Restaurant Suggestions for {} People, on {} at {}:\n'.format(cuisine, numberOfPeople, date, time) + restaurantSuggestions + '\nHope you enjoy your meal!\n\nRegards,\nDining Concierge'
    return reply, restaurantSuggestions


# function to send an email
def send_plain_email(fromEmailAddress, toEmailAddress, message):
    ses_client = boto3.client("ses", region_name="us-east-1")
    CHARSET = "UTF-8"

    response = ses_client.send_email(
        Destination={
            "ToAddresses": toEmailAddress,
        },
        Message={
            "Body": {
                "Text": {
                    "Charset": CHARSET,
                    "Data": message,
                }
            },
            "Subject": {
                "Charset": CHARSET,
                "Data": "Your restaurant recommendations",
            },
        },
        Source=fromEmailAddress,
    )
    print(response)


# function to get restaurantIds
def get_random_ids(number_of_hits):
    random_restaurant_indexes = []

    # get random restaurants
    if( number_of_hits > 3):
        random_restaurant_indexes = random.sample(range(0, number_of_hits - 1), 3)
    else:
        random_restaurant_indexes = random.sample(range(0, number_of_hits - 1), 1)

    return random_restaurant_indexes

#function to handle the lambda function
def lambda_handler(event, context):
    print(event)
    handle_queue_item()

# function to handle a queue item
def handle_queue_item():
    # create a boto3 client connect to the queue
    client = boto3.client('sqs')

    # get a list of queues, we get back a dict with 'QueueUrls' as a key with a list of queue URLs
    queues = client.list_queues(QueueNamePrefix='restaurantRequests')
    queue_url = queues['QueueUrls'][0]

    # get the response from the queue
    response = client.receive_message(
        QueueUrl=queue_url,
        AttributeNames=[
            'All'
        ],
        MaxNumberOfMessages=10,
        MessageAttributeNames=[
            'All'
        ],
        VisibilityTimeout=30,
        WaitTimeSeconds=0
    )
    print(response, "queue response")

    # if there are messages in the queue
    if len(response['Messages']) > 0:
        for message in response['Messages']:  # 'Messages' is a list
            print('message : ',message)
            js = json.loads(message['Body'])
            print('js : ',js)
            cuisine = js['cuisine']
            #phoneNumber = js['phoneNumber']
            url = 'https://search-restaurant-gkgknrtvkb4drescojoawsqwnm.us-east-1.es.amazonaws.com/restaurants/_search?q=cuisine:' + cuisine
            elastic_response = requests.get(url, auth = authent, headers={"Content-Type": "application/json"}).json()
            print("ElasticSearch response : ")
            print(elastic_response)
            number_of_hits = elastic_response['hits']["total"]
            randomIds = get_random_ids(number_of_hits)
            output, cache = generate_suggestions(randomIds, cuisine, js)
            email=js['email']
            print("Received email address : ")
            print(email)
            
            # send the message
            send_plain_email('yashikadhawan123@gmail.com', [email], str(output))

            # store the suggestions for next time
            table2response = table2.update_item(Key={'identity': 1}, UpdateExpression="set isFirstTime=:r, suggestions=:p",ExpressionAttributeValues={':r': True,':p': cache},ReturnValues="UPDATED_NEW")
            client.delete_message(QueueUrl=queue_url, ReceiptHandle=message['ReceiptHandle'])
    else:
        print('Queue is empty')
    
