# podcli
Command Line Podcast Manager

#### Install
Python3 only.
    
    pip3 install -r requirements.txt

Copy podcli_config.json.template to podcli_config.json and fill in the configs.

#### Usage
Add a podcast.

    python3 podcast.py -a http://example.com/podcast.xml
    
Refresh and download podcasts.

    python3 podcast.py -r -d
    
Sync podcasts.

    python3 podcast.py -s