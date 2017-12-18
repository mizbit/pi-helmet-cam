# pi-helmet-cam
Software for a Raspberry Pi Zero W motorcycle helmet camera.

Automatically starts recording when powered on, removing old videos if necessary, and uploads everything on youtube (convenient private storage with no visible limits) when network is available.

Based on similar implementation from [@nicolashahn](https://github.com/nicolashahn/pi-helmet-cam), but with improved software (auto merging of video files and youtube uploads) and mounted inside of the helmet instead of outside (this could change, but it's nice to have such a small camera which could be mounted anywhere).

## Necessary Hardware

- Raspberry Pi Zero W
- Raspberry Pi camera v2 with correct ribbon cable (Zero cable is different than full sized Pi's)
- MicroSD card
  - get one of the 'high endurance' ones since this will be writing HD video constantly
- Battery
  - Simplest solution is a smartphone external battery pack with magnetic microUSB cable (WSKEN X-Cable Round in my case -- make sure it connects properly by itself) and keep it in your jacket/backpack
    ![sample](https://user-images.githubusercontent.com/193864/34119829-8479579c-e45e-11e7-94ac-1a94802c5b65.gif)
- Camera housing/mounting
  - Cover both raspberry and camera with epoxy to make them resistant to water with electrical tape on top of it
    ![img_20171217_193939](https://user-images.githubusercontent.com/193864/34120125-8629157c-e45f-11e7-9a1f-daa03d68f30f.jpg)
    ![img_20171217_193957](https://user-images.githubusercontent.com/193864/34120126-8660c288-e45f-11e7-891d-acad509388e7.jpg)
    ![img_20171217_201024](https://user-images.githubusercontent.com/193864/34120127-86a0c0e0-e45f-11e7-958c-7530c8855843.jpg)
  - Velcro straps to secure the camera module, one glued on camera's back, another two strapped on helmet's velcro pads. One is "L" shaped in between the pads, another one on top of it to create "T" shape, and camera goes on top of "T". Could be impossible with your helmet though
    ![img_20171219_015646](https://user-images.githubusercontent.com/193864/34120320-2903c38c-e460-11e7-86b8-a262eee40e0a.jpg)
  - Electrical tape for mounting raspberry to the helmet
    ![img_20171219_010251](https://user-images.githubusercontent.com/193864/34120191-c344ca82-e45f-11e7-80aa-55c0eeb463d1.jpg)
    ![img_20171219_010307](https://user-images.githubusercontent.com/193864/34120192-c38032f2-e45f-11e7-8d8e-72e10ad19639.jpg)
    ![img_20171219_010328](https://user-images.githubusercontent.com/193864/34120193-c3bcfe12-e45f-11e7-930c-b7d0d3f46738.jpg)

## Setup Instructions

- Download [Rasbian Lite](https://downloads.raspberrypi.org/raspbian_lite_latest) and use [etcher](https://etcher.io/) to install it on an SD Card
- Create empty `ssh` file on boot partition created above to allow SSH access
- Configure and copy `wpa_supplicant.conf` file to setup wireless network
- Plug in the card and you should be ready to connect by e.g. `ssh pi@192.168.1.4` (lookup the IP using `arp -a` or something) with default password being `raspberry`
- Use `sudo raspi-config` to enable camera interface and change your password
- Clone this repo
- Generate `client_secret.json` from [Google Cloud Console](https://console.cloud.google.com/apis/credentials/oauthclient) (select 'Other' as application type) and click download JSON
- Copy `client_secret.json` onto your raspberry in project folder
- Run `make` from project folder – this will install dependencies and generate credentials based on your app secrets
- Run `sudo crontab -e` and add this line to the bottom:

    ```bash
    @reboot /home/pi/pi-helmet-cam/camera.py > /home/pi/pi-helmet-cam/cron.log 2>&1
    ```

You can check `cron.log` (latest session only) or `camera.log` (full history) for troubleshooting.
