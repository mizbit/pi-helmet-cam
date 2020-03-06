.PHONY : all credentials

all:
	sudo apt-get install -y fake-hwclock
	sudo curl https://bootstrap.pypa.io/get-pip.py | sudo python
	sudo pip install picamera google_auth_oauthlib google-api-python-client google-auth-httplib2 "httplib2<0.16.0"
	make credentials

credentials:
	python -c "__import__('pickle').dump(__import__('google_auth_oauthlib.flow').flow.InstalledAppFlow.from_client_secrets_file('client_secret.json', ['https://www.googleapis.com/auth/youtube.upload']).run_console(), open('.credentials', 'w'))"
