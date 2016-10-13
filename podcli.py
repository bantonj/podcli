#!/usr/bin/env python
"""Command Line Podcast Manager

You can add podcast RSS feeds, download podcasts, and sync them to a directory.
If the podcast ID3 tags are messy or unclear you can also automatically edit
them by setting the id3_edit config.

id3_edit structure:
    "id3_edit": {
        "podcast table id": {
          "album": "string to manually set album to",
          "artist": "string to manually set artist to",
          "title": "optional parameter: if set to copy_item will set to title
                    from the rss feed, otherwise if set to true will set
                    title to rss published date + album config"
        }
    }
"""
import json
import argparse
import urllib
import os
import sys
import shutil
import urlparse
import subprocess
import feedparser
from peewee import CharField, ForeignKeyField, DateTimeField, BooleanField, SqliteDatabase, Model, IntegrityError, TextField
from time import mktime
from datetime import datetime, timedelta
from fileDownloader.fileDownloader import DownloadFile
import mutagen
from mutagen import easyid3
from bs4 import BeautifulSoup
import unicodedata
import textwrap
from blessings import Terminal


def load_config():
    f = open('podcli_config.json', 'r')
    return json.load(f)

def get_enclosure(links):
    for x in links:
        if x['rel'] == 'enclosure':
            return x['href']


# Models
db = SqliteDatabase(load_config()['db'])


class PodcastTable(Model):
    feed = CharField(unique=True)
    title = CharField()

    class Meta:
        database = db # this model uses the podcli database

        
class EpisodeTable(Model):
    podcast = ForeignKeyField(PodcastTable, related_name='episodes')
    title = CharField()
    published = DateTimeField()
    enclosure = CharField()
    summary = TextField(null=True)
    new = BooleanField()

    class Meta:
        database = db # this model uses the podcli database

        
def create_tables():
    PodcastTable.create_table(fail_silently=True)
    EpisodeTable.create_table(fail_silently=True)

        
class PodCli(object):
    def __init__(self):
        self.config = load_config()
        self.download_dir = self.get_download_dir()
        self.check_download_dir()
        
    def get_download_dir(self):
        if 'download_folder' in self.config.keys():
            if os.path.isabs(self.config['download_folder']):
                return self.config['download_folder']
            else:
                return os.path.join(os.path.dirname(
                        os.path.realpath(sys.argv[0])),
                        self.config['download_folder'])
        else:
            return os.path.dirname(os.path.realpath(sys.argv[0]))
    
    def check_download_dir(self):
        if not os.path.exists(self.download_dir):
            os.mkdir(self.download_dir)
    
    def add_podcast(self, rss_url):
        feed = feedparser.parse(rss_url)
        try:
            PodcastTable.create(feed=rss_url, title=feed['feed']['title'])
        except IntegrityError:
            print 'Podcast already exists.'
        for pod in PodcastTable.select():
            print pod.title, pod.feed

    def get_summary(self, item):
        text = BeautifulSoup(item["summary"]).get_text()
        return unicodedata.normalize("NFKD", text)

    def print_summary(self, summary):
        if summary:
            term = Terminal()
            for line in textwrap.wrap(summary, term.width, initial_indent='    ',
                                      subsequent_indent='    '):
                print line

    def refresh_all(self):
        for pod in PodcastTable.select():
            feed = feedparser.parse(pod.feed)
            for item in feed['entries']:
                enclosure = self.get_enclosure(item)
                if not enclosure:
                    print '%s has no link, skipping' % item.title
                # If episode enclosure doesn't exist, add it
                if EpisodeTable.select().where(EpisodeTable.enclosure ==
                                               enclosure).count() < 1:
                    dt = datetime.fromtimestamp(mktime(
                            item['published_parsed']))
                    summary = self.get_summary(item)
                    print 'New Episode: ', pod.title, " -- ", item['title'], dt.strftime('%d/%m/%Y')
                    self.print_summary(summary)
                    print "\n"
                    EpisodeTable.create(podcast=pod, title=item['title'],
                                        published=dt, enclosure=enclosure,
                                        summary=summary, new=True)
                    
    def get_enclosure(self, episode):
        if 'links' not in episode.keys():
            return False
        for link in episode['links']:
            if link['rel'] == 'enclosure':
                return link['href']

    def is_downloaded(self, url, filename):
        if not os.path.exists(filename):
            return False
        df = DownloadFile(url, filename)
        filesize = df.getUrlFileSize()
        if not filesize:
            return False
        elif int(filesize) > os.path.getsize(filename):
            return False
        else:
            return True

    def download_all_new(self):
        for item in EpisodeTable.select().where(EpisodeTable.new):
            filename = self.get_fullpath(item.enclosure)
            if not self.is_downloaded(item.enclosure, filename):
                print 'downloading: ', item.title
                self.download(item.enclosure, filename)
                self.check_id3_edit(item.podcast.id, filename, item)
            
    def download(self, url, fullpath):
        df = DownloadFile(url, fullpath)
        df.download()
        return df.localFileName
        
    def get_fullpath(self, url):
        return os.path.join(self.download_dir, urllib.unquote(
                os.path.basename(urlparse.urlparse(url).path)))
    
    def list(self, which):
        if which == 'new':
            for item in EpisodeTable.select().where(EpisodeTable.new):
                print str(item.id), 'New Ep: ', item.title, item.published.strftime('%d/%m/%Y')
                self.print_summary(item.summary)
                print "\n"
        if which == 'pod':
            for item in PodcastTable.select():
                print str(item.id), item.title
                
    def check_id3_edit(self, podcast_id, filename, item):
        if str(podcast_id) in self.config['id3_edit'].keys():
            id3_config = self.config['id3_edit'][str(podcast_id)]
            album = id3_config['album']
            artist = id3_config['artist']
            if 'title' in id3_config.keys():
                if id3_config['title'] == 'copy_item':
                    title = item.title
                else:
                    title = item.published.strftime('%d/%m-') + album
                self.edit_id3(filename, album, artist, title)
            else:

                self.edit_id3(filename, album, artist)
    
    def edit_id3(self, filename, album, artist, title=None):
        try:
            audio = easyid3.EasyID3(filename)
        except mutagen.id3.ID3NoHeaderError:
            audio = mutagen.File(filename, easy=True)
            audio.add_tags()
        audio["album"] = album
        audio["artist"] = artist
        audio["genre"] = u"Podcast"
        if title:
            audio["title"] = title
        audio.save()

    def sync(self, which):
        if which == 'new':
            for item in EpisodeTable.select().where(EpisodeTable.new):
                filename = self.get_fullpath(item.enclosure)
                if not os.path.exists(filename):
                    print "Haven't downloaded %s yet." % os.path.basename(filename)
                    continue
                print 'Copying: ', item.title
                if self.config["folder_mode"]:
                    pod_dir = os.path.join(self.config['sync_to'],
                                               item.podcast.title)
                    writetopath = os.path.join(pod_dir,
                                               os.path.basename(filename))
                    if not os.path.exists(pod_dir):
                        os.mkdir(pod_dir)
                else:
                    writetopath = os.path.join(self.config['sync_to'],
                                               os.path.basename(filename))
                shutil.copyfile(filename, writetopath)
                item.new = False
                item.save()
                
    def delete_podcast(self, podcast_id):
        podcast = PodcastTable.select().\
            where(PodcastTable.id == podcast_id).get()
        podcast.delete_instance(recursive=True)
        
    def delete_old(self, location):
        if location == 'local':
            self.delete_files_local(self.download_dir)
        elif location == 'player':
            self.delete_files(self.config['sync_to'])
            
    def delete_files(self, direc, num_days=14):
        cur_dir = os.getcwd()
        os.chdir(direc)
        pod_dirs = os.listdir(direc)
        for pod_dir in pod_dirs:
            files = os.listdir(pod_dir)
            os.chdir(pod_dir)
            for filename in files:
                if (datetime.now() - datetime.fromtimestamp(os.path.getctime(filename))).days > num_days:
                    print 'removing %s' % (str(filename))
                    os.remove(filename)
            os.chdir(direc)
        os.chdir(cur_dir)
        
    def delete_files_local(self, direc, num_days=14):
        cur_dir = os.getcwd()
        os.chdir(direc)
        files = os.listdir(direc)
        for filename in files:
            if (datetime.now() - datetime.fromtimestamp(os.path.getctime(filename))).days > num_days:
                print 'removing %s' % (str(filename))
                os.remove(filename)
        os.chdir(cur_dir)
        
    def mark_old(self, days, podcast_id=False):
        if podcast_id:
            podcast = PodcastTable.select().where(PodcastTable.id == podcast_id).get()
            episodes = EpisodeTable.select().\
                where(EpisodeTable.new, EpisodeTable.podcast == podcast)
        else:
            episodes = EpisodeTable.select().where(EpisodeTable.new)
        for item in episodes:
            if item.published < datetime.now()-timedelta(days):
                print 'Marking old: ', item.title
                item.new = False
                item.save()
    
    def eject(self):
        subprocess.call(['diskutil', 'unmount', self.config['eject_point']])
        
        
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-a", "--add_podcast", help="add new podcast")
    parser.add_argument("-r", "--refresh_all", help="refresh all podcasts", nargs='?', const=True)
    parser.add_argument("-d", "--download_all_new", help="download all new podcasts", nargs='?', const=True)
    parser.add_argument("-l", "--list", help="with no argument lists all new podcasts, with argument pod it lists all podcasts", nargs='?', const='new')
    parser.add_argument("-s", "--sync", help="sync all new podcasts", nargs='?', const='new')
    parser.add_argument("--delete", help="delete podcast, must specify podcast id")
    parser.add_argument("--delete_old", help="delete old episode downloads, defaults to local episodes, other option player", nargs='?', const='local')
    parser.add_argument("--mark_old", help="mark episodes older than arg as old", nargs='?', const='7')
    parser.add_argument("--mark_old_podcast", help="specifies mark_old podcast to mark old episodes", nargs='?', const=False)  
    parser.add_argument("-e", "--eject", help="eject player", nargs='?', const=True)
    args = parser.parse_args()
    podcli = PodCli()
    
    if args.add_podcast:
        podcli.add_podcast(args.add_podcast)
    if args.refresh_all:
        podcli.refresh_all()
    if args.download_all_new:
        podcli.download_all_new()
    if args.list:
        podcli.list(args.list)
    if args.sync:
        podcli.sync(args.sync)
    if args.delete:
        podcli.delete_podcast(args.delete)
    if args.delete_old:
        podcli.delete_old(args.delete_old)
    if args.eject:
        podcli.eject()
    if args.mark_old:
        podcli.mark_old(int(args.mark_old), args.mark_old_podcast)