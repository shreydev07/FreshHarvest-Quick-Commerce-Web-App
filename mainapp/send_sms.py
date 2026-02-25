import requests

url = "http://sms.bulkssms.com/submitsms.jsp"
params = {
    "user": "BRIJESH",
    "key": "066c862acdXX",
    "mobile": "0945318798",
    "message": "Thanks for enquiry we will contact you soon.\n\n-Bulk SMS",
    "senderid": "UPDSMS",
    "accusage": "1",
    "entityid": "1201159543060917386",
    "tempid": "1207169476099469445"
}

response = requests.get(url, params=params)
print("Response:", response.text)
