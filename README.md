Cloud-enabled Bathroom Scale
------------------------------
Cloud-enable the EB9121 bathroom scale with an [LIRC](http://www.lirc.org/) receiver.

The EB9121 bathroom scale transmits weight measurements to a remote display unit using
infrared. The infrared protocol was reverse-engineered and is thus able to be interpreted 
using this script. This script logs measurements to a Google Docs spreadsheet for 
graphing/exporting.

This script uses the [oauth2client library](https://github.com/google/oauth2client/) to 
authorize access to Google Docs, and the [gspread library](https://github.com/burnash/gspread) 
to interact with Spreadsheets on Google Docs. Note that oauth2client does NOT support Python 3.


Installation
-------------
The installation process for this script is rather involved because of the 
OAuth 2.0 access to the Google Docs spreadsheet.

Steps 3 & 4 is a one-time process of creating a Client ID for this script. I 
could supply the one I created, but I'm worried of abuse, so you will have to 
do this yourself.

Step 5 is the similar to the setup required for the [Adafruit tutorial for humidity logging](https://learn.adafruit.com/dht-humidity-sensing-on-raspberry-pi-with-gdocs-logging/connecting-to-googles-docs-updated).

Steps 6 & 7 verify that the setup is working as expected.


1. Clone the repository:

        hg clone https://bitbucket.org/geekman/cloud-bathroom-scale

2. Create the `virtualenv` to download required the Python dependencies. If your system has
   both Python 2 and 3 installed, you might need to use `virtualenv2` instead.

        cd cloud-bathroom-scale
        virtualenv venv
        source venv/bin/activate

3. Run the `mkwheels` script to download dependencies and 
   unpack them into the `deps` directory:

        ./mkwheels
        unzip -d deps deps.zip

4. Now the virtualenv is no longer needed. You can now deactivate and discard it:

        deactivate
        rm -rf venv

5. Expose the lirc device by adding a dtoverlay to `/boot/config.txt`:

        dtoverlay=lirc-rpi,gpio_in_pin=4

6. Create a project and a new Client ID at the [Google Developers Console](https://console.developers.google.com/).
   Select "Installed application" under "Application Type".

7. Download the JSON file for the generated Client ID. Ensure that the filename is `client_secrets.json`.

8. Create a new Spreadsheet in Google Docs and delete off all the rows. Find
   the document "key" in the URL, which should look something like this:

        https://docs.google.com/spreadsheets/d/<DOCUMENT_KEY_HERE>/edit

9. Run the script to test that it works by passing the `--test` argument:

        ./cloud-bathroom-scale.py --test <DOCUMENT_KEY>

10. Check that a row has been added to the Spreadsheet with the current time.


Normal Usage
-------------
The script needs to be started, like so:

    ./cloud-bathroom-scale.py <DOCUMENT_KEY>

When you step onto the scale, the bathroom scale should emit the measurements 
via infrared and will be picked up by the script. When the weight is stable,
the reading is recorded into the Google Docs spreadsheet.

A status LED can be added to visually indicate to the user if the measurements 
are being picked up by the IR receiver. The LED blinks to indicate this, and 
when the weight is being recorded, the LED turns solid for a few seconds, then 
turns off. The GPIO pin connected to the LED can be specified by the `--led` 
argument.

If there are problems, you can pass the `--debug` argument to see if weight 
measurements are being correctly recognized.

A systemd service file has been included (tested on Arch Linux) to
automatically start the logging script on boot. You will need to copy this file
into `/etc/systemd/system/multi-user.target.wants/` and modify the
`Environment=` lines accordingly. For "security", the script runs as my user
and this can be specified by the `User=` line.


License
--------
cloud-bathroom-scale is licensed under the 3-clause ("modified") BSD License.

Copyright (C) 2014 Darell Tan

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions
are met:

1. Redistributions of source code must retain the above copyright
   notice, this list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright
   notice, this list of conditions and the following disclaimer in the
   documentation and/or other materials provided with the distribution.
3. The name of the author may not be used to endorse or promote products
   derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE AUTHOR ``AS IS'' AND ANY EXPRESS OR
IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES
OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY DIRECT, INDIRECT,
INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT
NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF
THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

