# pi-helmet-cam
Software for a Raspberry Pi Zero W motorcycle helmet camera.

Automatically starts recording when powered on, removing old videos if necessary, and uploads everything on youtube when network is available.

## Necessary Hardware

- Raspberry Pi
  - Zero/Zero Wireless ideally
- Raspberry Pi camera
  - an offical Raspberry Pi camera is a safe bet
  - with correct ribbon cable (Zero cable is different than full sized Pi's, also should get at least 6" long)
- MicroSD card
  - get one of the 'high endurance' ones since this will be writing HD video constantly
- Battery
  - Simplest solution is a smartphone external battery pack with a microUSB cable (magnetic is the best option)
- Camera housing/mounting
  - Cover both raspberry and camera with epoxy to make them resistant to water with electrical tape on top of it
  - Velcro straps to secure the camera module
  - Electrical tape for mounting raspberry to the helmet

## Setup Instructions

#### Set up Raspberry Pi (headless)

- Download [Rasbian Lite](https://downloads.raspberrypi.org/raspbian_lite_latest) and use [etcher](https://etcher.io/) to install it on an SD Card
- Create empty `ssh` file on boot partition created above to allow SSH access
- Configure and copy `wpa_supplicant.conf` file to setup wireless network
- Plugin the card and you should be ready to connect by e.g. `ssh pi@192.168.1.4` (lookup the IP using `arp -a` or something) with default password being `raspberry`
- Use `sudo raspi-config` to enable camera interface and change your password
- Clone this repo
- Generate `client_secret.json` from [Google Cloud Console](https://console.cloud.google.com/apis/credentials/oauthclient) (select 'Other' as application type) and click download JSON
- Copy `client_secret.json` onto your raspberry in project folder
- Run `make` from project folder – this will install dependencies and generate credentials based on your app secrets
- Run `sudo crontab -e` and add this line to the bottom:

    @reboot /home/pi/pi-helmet-cam/camera.py > /home/pi/pi-helmet-cam/cron.log 2>&1

You can check `cron.log` (latest session only) or `camera.log` (full history) for troubleshooting.
