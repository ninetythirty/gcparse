#!/usr/bin/env python

# No copyright, ninetythirty, February 2014.
#
# gcparse.py
# Usage: gcparse.py [-h] [-n] [-a] mbox
#
# This program frees your Gmail chat/instant message history from Google. It
# produces a nicely-formatted plain text record of your chats, organized by
# person: one file for each person you've chatted with. It also makes XML-
# formatted conversations, if you're into that sort of thing.
#
# To use gcparse, you have to feed it an mbox file from a Google Mail
# "archive". To create your mail archive, log in to any Google service and
# click through Account/Data tools/select data to download/Create an archive.
#
# gcparse ONLY writes into its data directory 'gcparse_data' which it creates
# next to itself. It's always okay to delete the entire data directory and
# start over.
#
# About the name map
#
# Google chat identifies people by their addresses, so without modification a
# chat line will look something like this:
# 
#    23:59  crowley.beast666@thelema.org: Do as thou wilt.
# 
# The optional name map can turn that line into:
# 
#    23:59  Aleister: Do as thou wilt.
# 
# Much nicer, right? gcparse creates an empty name map the first time it runs,
# it's called 'name_map' and you can find it in the data directory. You have to
# fill in the names yourself. It's easy, just type the name you want to use
# next to the address you want to map and save the file. You can use the name
# map for select addresses only--empty names will be displayed as addresses.
# You can also map different addresses to the same name and gcparse will do the
# right thing.
# 
# One other point: 'my_address' in the name map is a required field. gcparse
# should be able to guess your address, but if text-formatted chats come out
# in funny places you should check that 'my_address' really is your address.
# If it's wrong, no problem, just fix it and re-run.
#
# About the -n, --no-wrap option
#
# By default, individual chat messages that span multiple lines will have their
# line breaks recalculated when formatted for text. To preserve line breaks,
# use this option. There are only two reasons to consider using it: If you have
# a lot of PRE-FORMATTED MULTI-LINE messages, or if you chat with people with
# very long names. The default should be fine for just about everyone.
#
# About the -a, --analyze option
#
# If you want to manually fix conversation threading errors (see discussion
# below), this option helpfully prints a list of out-of-order timestamps which
# are very good proxies for type III threading errors.

# This program requires Python 3 and lxml (http://lxml.de).
#
# I tried to write this in Python 2.x but it wasn't up to the task--too many
# problems with character encodings, etc. (Hey, an actual reason to use Python
# 3!) I also tried hard to avoid external dependencies but gave up. ElementTree
# in the Python standard library is a wreck. It's unusuable even for simple
# things and the documentation is poor. Not that lxml is a shining star.

# A few words on Google and your data
# 
# Google pays lip service to your data being yours, but their hearts don't seem
# to be in it. For example, there's currently a very bad bug with Google's
# archive files: THE ARCHIVES ARE INCOMPLETE. I reported the bug on February 2,
# 2014: "Using the Accounts web interface, I downloaded an achive of all my
# gmail messages ('Include all of your mail'), and there are missing messages.
# For example, in the archive xxxxxxxx@gmail.com-20140202T201547Z-Mail.zip, the
# message with Message-ID: xxxxxxx.xxxxxxxxxxxxxxxxxx.chat@gmail.com is
# missing". This seems to be a problem with old-style chats, and it's difficult
# to overstate the severity. In my case, over 30% of my 2843 old-style
# conversations are missing from the archive. This isn't a "bug", it's
# completely broken software.
# 
# Another example: have you looked at your recent Google chats in Apple Mail?
# Each line you or your buddy typed is a separate message, and there's no way
# to connect the messages into conversations because apparently Google strips
# the threading headers (X-GM-THRID and X-Gmail-Labels) from chat messages
# received via IMAP. It also seems that Google prevents users from accessing
# any chat headers at all in the Gmail web UI (headers can be shown for regular
# emails using the "show original" command). But don't worry, you can still
# view threaded conversations in that poor and worsening web interface.
# 
# It wasn't always like this--chats were neatly threaded before about May
# 2013. For now, critical headers aren't stripped from "archive" data.

# Limitations
#
# Group chat: Group chat isn't supported.
#
# Time: Text-formatted chats use military time adjusted for the timezone your
# computer thinks it's in when you run gcparse. If at some point you chatted
# from a different timezone, the text-formatted time will be wrong. There's no
# way around this other than manually editing the timestamps because there
# isn't any geo data in the archive file to match time to place. Old-style XML
# chats use Unix time with milliseconds, but milliseconds aren't preserved in
# new-style chat messages (in use since about May 2013). For new-style
# messages, the program writes fake milliseconds starting at zero in order to
# preserve message sequence. 
#
# Conversation threading: Google organizes messages into conversations using
# thread IDs. Most of the time the messages collected into one THRID are an
# accurate representation of what a human would think of as one conversation,
# but there are three types of failures that sometimes occur: Multiple
# conversations can be incorrectly grouped into one THRID; single conversations
# can be split across multiple THRIDs; worst of all, non-contiguous lines from
# a single conversation can be sharded out into different THRIDs, garbling
# parts of a conversation completely (type III). None of these problems can be
# solved automatically. Fortunately, THRID errors seem to be infrequent. In my
# personal corpus of 2654 conversations, there are 9 THRID errors (0.3%), 6 of
# which are type III. 

import argparse
from collections import defaultdict
import datetime
import glob
import html.entities
from html.parser import HTMLParser
import json
from lxml import etree
import mailbox
from operator import itemgetter
import os
import quopri
import shutil
import sys
import textwrap
import xml.etree.ElementTree as ET

# -----------------------------------------------------------------------------
def clean_xml_payload(payload):
    # Clean up an XML mail payload in the following ways:
    #   1. Remove the first three lines--they're not XML
    #   2. Decode quoted-printable encoding, if necessary
    stripped = '\n'.join(payload.as_string().split('\n')[3:])
    if payload['Content-Transfer-Encoding'] == 'quoted-printable':
        charset = payload.get_content_charset()
        return bytes.decode(quopri.decodestring(stripped), charset)
    else:
        return stripped

# -----------------------------------------------------------------------------
def clean_html_payload(payload, transfer_encoding, charset):
    # Clean up an HTML mail payload in the following ways:
    #   1. Decoded quoted-printable encoding, if necessary
    #   2. De-duplicate double-newline line endings
    #   3. Replace line break tag with newline
    #   4. Remove all HTML tags
    #   5. Unescape character entity refs and numeric character refs
    if transfer_encoding == 'quoted-printable':
        payload = bytes.decode(quopri.decodestring(payload), charset)
    deduped_line_ends = payload.replace('\n\n', '\n')
    newlined = deduped_line_ends.replace('<br>', '\n')
    # Manually unescape because it isn't built in to the Python standard
    # library and lxml's unescaping is buggy
    class MyHTMLParser(HTMLParser):
        def __init__(self):
            HTMLParser.__init__(self)
            self.data = []
        def handle_data(self, data):
            self.data.append(data)
        def handle_entityref(self, name):
            self.data.append(html.entities.entitydefs[name])
        def handle_charref(self, name):
            self.data.append(chr(int(name)))
    parser = MyHTMLParser()
    parser.feed(newlined)
    return ''.join(parser.data).strip()

# -----------------------------------------------------------------------------
def remove_namespace(tree, namespace):
    # Remove an XML namespace from tree
    for element in tree.iter():
        if element.tag.startswith(namespace):
            element.tag = element.tag[len(namespace):]

# -----------------------------------------------------------------------------
def tag_conversations(xml_dir):
    # xml_dir is a directory where each file is a collection of chat message
    # elements representing a single conversation. Enclose conversations in
    # conversation tags
    num_conversations = 0
    for filename in glob.glob('{0}/*.conv'.format(xml_dir)):
        num_conversations += 1
        with open(filename, 'r') as f:
            conversation = f.read()
        with open(filename, 'w') as f:
            f.write('<conversation>\n')
            f.write(conversation)
            f.seek(0, 2)
            f.write('</conversation>\n')
    return num_conversations

# -----------------------------------------------------------------------------
def find_ooo_timestamps(source_dir):
    # Search XML conversations for out-of-order timestamps. Messages must be
    # organized into files by THRID such that each THRID is its own file with
    # all messages with that THRID
    num_ooo = 0
    prev_thrid = 0
    prev_ts = 0
    for filename in glob.glob('{0}/*.conv'.format(source_dir)):
        with open(filename, 'r') as f:
            thrid = int(os.path.basename(filename).split('.')[0])
            tree = etree.parse(f)
            messages = tree.xpath('//message')
            for m in messages:
                from_field = m.attrib['from']
                to_field = m.attrib['to']
                body = m.xpath('./body')[0].text
                ts = int(m.xpath('./time')[0].attrib['ms'])
                if ts < prev_ts:
                    if from_field in (prev_from_field, prev_to_field) and to_field in (prev_from_field, prev_to_field):
                        num_ooo += 1
                        print('! Out-of-order timestamp, {0}:{1} \'{2}\' < {3}:{4} \'{5}\''.format(thrid, ts, body, prev_thrid, prev_ts, prev_body), file=sys.stdout)
                prev_ts = ts
                prev_from_field = from_field
                prev_to_field = to_field
                prev_body = body
            prev_thrid = thrid
    print('Out-of-order timestamps: {0}'.format(num_ooo), file=sys.stdout)

# -----------------------------------------------------------------------------
def parse_master_mbox(master_mbox_file, chats_mbox_file):
    print('Parsing mbox \'{0}\'... '.format(master_mbox_file), file=sys.stdout)
    sys.stdout.flush()
    master_mbox = mailbox.mbox(master_mbox_file)
    chats_mbox = mailbox.mbox(chats_mbox_file)
    num_messages = 0
    num_chats = 0

    for message in master_mbox:
        num_messages += 1
        if message['X-Gmail-Labels'] and 'Chat' in message['X-Gmail-Labels']:
            # ALL gmail chats are labeled 'Chat'
            num_chats += 1
            chats_mbox.add(message)

    print('    Total messages: {0}'.format(num_messages), file=sys.stdout)
    print('    {0} chat messages stored in \'{1}\''.format(num_chats, os.path.basename(chats_mbox_file)), file=sys.stdout)
    print('DONE', file=sys.stdout)

# -----------------------------------------------------------------------------
def separate_old_from_new_chats(chats_all_mbox_file, chats_old_mbox_file, chats_new_mbox_file):
    # Somewhere around 2013-05-01 Google changed its chat format. Old chat is
    # custom XMPP-like XML, new chat is mail message-based text/html.
    print('Separating old-style from new-style chats... ', file=sys.stdout)
    sys.stdout.flush()
    chats_all_mbox = mailbox.mbox(chats_all_mbox_file)
    chats_old_mbox = mailbox.mbox(chats_old_mbox_file)
    chats_new_mbox = mailbox.mbox(chats_new_mbox_file)
    num_messages = 0
    num_old_chats = 0
    num_new_chats = 0

    for message in chats_all_mbox:
        num_messages += 1
        if message.is_multipart():
            # ALL old-style chats have the message in a 2-part multipart
            # payload: the first part containts the full XML chat, the second
            # contains a useless HTML representation of the chat
            num_old_chats += 1
            chats_old_mbox.add(message)
        else:
            # ALL new-style chats have the message in a non-multipart payload:
            # the payload is just a string containing the chat content
            num_new_chats += 1
            chats_new_mbox.add(message)

    print('    Chat messages: {0}'.format(num_messages), file=sys.stdout)
    print('    Old-style: {0} chat messages stored in \'{1}\''.format(num_old_chats, os.path.basename(chats_old_mbox_file)), file=sys.stdout)
    print('    New-style: {0} chat messages stored in \'{1}\''.format(num_new_chats, os.path.basename(chats_new_mbox_file)), file=sys.stdout)
    print('DONE', file=sys.stdout)

# -----------------------------------------------------------------------------
def parse_old_conversations(mbox_file, xml_dir, addresses):
    # Until about 2013-05-01 Google used XMPP-like XML for chat
    print('Parsing old-style XML chats... ', file=sys.stdout)
    sys.stdout.flush()
    mbox = mailbox.mbox(mbox_file)
    num_messages = 0
    num_malformed = 0 # no XML
    num_groupchats = 0

    for message in mbox:
        num_messages += 1
        thread_id = message['X-GM-THRID']
        payload = message.get_payload(i=0)
        transfer_encoding = payload['Content-Transfer-Encoding']
        content_type = payload.get_content_type()
        if content_type != 'text/xml':
            # These are either empty messages or email messages that Google
            # confused while attempting to blur the distinction between chat
            # and email. In the latter case, we only care about chat messages
            # here, but the message should be correctly parsed as email
            num_malformed += 1
        else:
            # Message contains good XML, clean it up
            payload_cleaned = clean_xml_payload(payload)
            tree = etree.fromstring(payload_cleaned)
            if tree.xpath('//cli:message[@type="groupchat"]', namespaces={'cli': 'jabber:client'}):
                # Skip group chats
                num_groupchats += 1
                continue
            # Python's ElementTree fails miserably here, use lxml
            xpaths = []
            # Google elements
            signature_xpath = tree.xpath('//met:google-mail-signature', namespaces={'met': 'google:metadata'})
            xpaths.append(signature_xpath)
            delay_xpath = tree.xpath('//jxd:x', namespaces={'jxd': 'jabber:x:delay'})
            xpaths.append(delay_xpath)
            nosave_xpath = tree.xpath('//nos:x', namespaces={'nos': 'google:nosave'})
            xpaths.append(nosave_xpath)
            record_xpath = tree.xpath('//arc:record', namespaces={'arc': 'http://jabber.org/protocol/archive'})
            xpaths.append(record_xpath)
            xhtml_xpath = tree.xpath('//xht:html', namespaces={'xht': 'http://www.w3.org/1999/xhtml'})
            xpaths.append(xhtml_xpath)
            xhtmlim_xpath = tree.xpath('//xim:html', namespaces={'xim': 'http://jabber.org/protocol/xhtml-im'})
            xpaths.append(xhtmlim_xpath)
            gap_xpath = tree.xpath('//con:gap', namespaces={'con': 'google:archive:conversation'})
            xpaths.append(gap_xpath)
            # Jabber "composing" element (someone was typing)
            composing_xpath = tree.xpath('//eve:x', namespaces={'eve': 'jabber:x:event'})
            # Remove junk elements (there are a lot of them)
            xpaths.append(composing_xpath)
            for x in xpaths:
                for dud in x:
                    dud.getparent().remove(dud)
            # Strip Google and experimental(?) AIM attributes
            etree.strip_attributes(tree,
                                   'iconset',
                                   '{google:internal}cid',
                                   '{google:internal}sequence-no',
                                   '{google:internal}time-stamp',
                                   '{google:internal}interop-stanza',
                                   '{google:internal}dual-delivery',
                                   '{google:internal}interop-disable-legacy-archiver',
                                   '{google:aim}new-session',
                                   )
            # Clean up namespaces
            remove_namespace(tree, '{jabber:client}')
            remove_namespace(tree, '{google:archive:conversation}')
            remove_namespace(tree, '{google:timestamp}')
            etree.cleanup_namespaces(tree)
            # Remove /resource from message 'from' and 'to' attributes
            for m in tree.xpath('//message'):
                from_field = m.attrib['from'].split('/')[0]
                to_field = m.attrib['to'].split('/')[0]
                m.attrib['from'] = from_field
                m.attrib['to'] = to_field
                # Record addresses for name map
                addresses[from_field] += 1
                addresses[to_field] += 1

            # Write out data
            f = open('{0}/{1}.conv'.format(xml_dir, thread_id), 'a') # append
            # Format manually b/c lxml's pretty print makes a TON of mistakes
            prev_m_as_string = ''
            for m in tree.xpath('//message'):
                m_as_string = etree.tostring(m)
                # Gotcha: When xpath() is used on an Element, if the XPath
                # expression is relative it's evaluated against the element.
                # If the expression is absolute it's evaluated against the tree
                to_field = m.attrib['to']
                from_field = m.attrib['from']
                body = m.xpath('./body')
                # In the case of sequential messages with identical timestamps,
                # we have to rely on line order in the mbox to order messages
                time_ms = m.xpath('./time')[0].attrib['ms']
                if m_as_string != prev_m_as_string and len(body) != 0:
                    # Don't print duplicate messages (sometimes the entire
                    # message including timestamp is repeated), don't print
                    # empty messages
                    print('  <message to="{0}" from="{1}">'.format(to_field, from_field), file=f)
                    print('    <body>{0}</body>'.format(html.escape(body[0].text)), file=f)
                    print('    <time ms="{0}"/>'.format(time_ms), file=f)
                    print('  </message>', file=f)
                prev_m_as_string = m_as_string
            f.close()

    num_parsed = num_messages - num_malformed - num_groupchats
    if num_malformed:
        print('    Malformed: {0}'.format(num_malformed), file=sys.stdout)
    if num_groupchats:
        print('    Group chats: {0} (unsupported)'.format(num_groupchats), file=sys.stdout)
    print('    Messages parsed: {0}'.format(num_parsed), file=sys.stdout)
    print('DONE', file=sys.stdout)
    return num_parsed

# -----------------------------------------------------------------------------
def parse_new_conversations(mbox_file, xml_dir, addresses):
    # After about 2013-05-01 Google stopped using XMPP-like XML for chats,
    # they switched to a mail message-based text/html format
    print('Parsing new-style chats... ', file=sys.stdout)
    sys.stdout.flush()
    mbox = mailbox.mbox(mbox_file)
    num_messages = 0
    num_empty = 0
    prev_timestamp_ms = ''
    increment_ms = 1

    for message in mbox:
        num_messages += 1
        thread_id = message['X-GM-THRID']
        if not message['From']:
            # Missing 'From' field is a way to identify an empty message
            num_empty += 1
        else:
            transfer_encoding = message['Content-Transfer-Encoding']
            charset = message.get_content_charset()
            payload = message.get_payload()
            cleaned_payload = clean_html_payload(payload, transfer_encoding, charset)
            date_components = message['Date'].split(' ')
            timestamp = datetime.datetime.strptime(' '.join(date_components[0:6]), '%a, %d %b %Y %H:%M:%S %z')
            # Milliseconds aren't preserved in new-style chat messages. Even if
            # they were, we'd have to rely on line order in the mbox to order
            # sequential messages with identical timestamps
            timestamp_ms = ''.join((timestamp.strftime('%s'), '000'))
            if prev_timestamp_ms == timestamp_ms:
                # In the case of duplicate timestamps, since we're writing
                # fake milliseconds anyway, increment to preserve message order
                prev_timestamp_ms = timestamp_ms
                timestamp_ms = str(int(timestamp_ms) + increment_ms)
                increment_ms += 1
            else:
                prev_timestamp_ms = timestamp_ms
                increment_ms = 1
            from_field = message['From'].rsplit(' ', 1)[1].strip('<>')
            to_field = message['To'].rsplit(' ', 1)[1].strip('<>')
            # Record addresses for name map
            addresses[from_field] += 1
            addresses[to_field] += 1

            # Write out data
            f = open('{0}/{1}.conv'.format(xml_dir, thread_id), 'a') # append
            print('  <message to="{0}" from="{1}">'.format(to_field, from_field), file=f)
            print('    <body>{0}</body>'.format(html.escape(cleaned_payload)), file=f)
            print('    <time ms="{0}"/>'.format(timestamp_ms), file=f)
            print('  </message>', file=f)

    num_parsed = num_messages - num_empty
    if num_empty:
        print('    Empty: {0}'.format(num_empty), file=sys.stdout)
    print('    Messages parsed: {0}'.format(num_parsed), file=sys.stdout)
    print('DONE', file=sys.stdout)
    return num_parsed

# -----------------------------------------------------------------------------
def format_xml_conversations_as_text(source_dir, dest_dir, my_address, name_map, no_wrap):
    print('Formatting XML conversations as text... ', file=sys.stdout)
    sys.stdout.flush()
    # separator must match separator in sort_text_conversations()
    separator = '-'*40
    line_width = 79
    time_width = 5 # clock time is always 5 chars wide
    time_padding = 2
    total_time_width = time_width + time_padding
    name_padding = 1

    for filename in glob.glob('{0}/*.conv'.format(source_dir)):
        with open(filename, 'r') as source_file:
            # Python's ElementTree actually works here
            tree = ET.parse(source_file)
        # Guess who the first message is from, swap if wrong
        first_message = tree.findall('message[1]')[0]
        other = first_message.attrib['from']
        me = first_message.attrib['to']
        if other == my_address:
            me, other = other, me
        if other in name_map and name_map[other] != '':
            other = name_map[other]
        if me in name_map and name_map[me] != '':
            me = name_map[me]
        # Calculate widths
        longest_name_width = max((len(me), len(other)))
        total_name_width = longest_name_width + 1 + name_padding # includes ':'
        wrap_width = line_width - total_time_width - total_name_width
        subsequent_indent = line_width - wrap_width

        # Write out data
        f = open('{0}/{1}.conv.unsorted'.format(dest_dir, other), 'a') # append
        # Get the first stamp, so we can set the conversation date
        first_stamp = first_message.findall('time[1]')[0].attrib['ms']
        # Convert epoch time to local (truncate miliseconds). This correctly
        # accounts for historical timezone offsets
        local_time = datetime.datetime.fromtimestamp(int(first_stamp[:10]))
        print(separator, end='', file=f)
        prev_local_date = None
        prev_local_time = None
        prev_who = ''
        for m in tree.iter('message'):
            # Time
            stamp = m.findall('time[1]')[0].attrib['ms']
            # Convert to local, as above
            local_date = datetime.datetime.fromtimestamp(int(stamp[:10])).strftime('%Y-%m-%d')
            local_time = datetime.datetime.fromtimestamp(int(stamp[:10])).strftime('%H:%M')
            if prev_local_date != local_date:
                print('\n{0}\n'.format(local_date), file=f)
                prev_local_date = local_date
            if prev_local_time != local_time:
                print('{0}{1}'.format(local_time, ' '*time_padding), end='', file=f)
                prev_local_time = local_time
            else:
                print(' '*total_time_width, end='', file=f)

            # Who
            who = m.attrib['from']
            if who in name_map and name_map[who] != '':
                who = name_map[who]
            if prev_who != who:
                print('{0}:{1}'.format(who, ' '*(total_name_width-len(who)-1)), end='', file=f)
                prev_who = who
            else:
                print(' '*total_name_width, end='', file=f)

            # Body
            body = m.findall('body[1]')[0].text
            if no_wrap:
                # Don't wrap lines, left-pad manually
                lines = body.splitlines()
                print(lines[0], file=f)
                for line in lines[1:]:
                    print(''.join((' '*subsequent_indent, line)), file=f)
            else:
                # Note: textwrapper's subsequent_indent attribute seems to be
                # bugged, it produces subsequent lines that are too short. It's
                # easy to indent manually
                lines = textwrap.wrap(body, width=wrap_width)
                print(lines[0], file=f)
                for line in lines[1:]:
                    print(''.join((' '*subsequent_indent, line)), file=f)

    print('DONE', file=sys.stdout)

# -----------------------------------------------------------------------------
def sort_text_conversations(source_dir, dest_dir):
    # We'd rather sort XML by timestamp but that isn't necessarily effective
    # because XML chats are organized by THRID, THRIDs don't necessarily
    # increase monotonically with time, and it's possible to have out of order
    # timestamps across THRID. So we sort text
    print('Sorting text conversations by person... ', file=sys.stdout)
    sys.stdout.flush()
    num_conversations = 0
    # separator must match separator in format_xml_conversations_as_text()
    separator = '-'*40
    sentinel = ''.join((separator, '\n'))

    for filename in glob.glob('{0}/*.conv.unsorted'.format(source_dir)):
        num_conversations += 1
        offsets = []
        # When opening a file in text mode, file.tell() and file.seek() use
        # bytes, but file.read() uses characters. In binary mode, all three use
        # bytes. Of course this is undocumented. You've really got strings and
        # bytes figured out, Python 3.3!
        with open(filename, 'r') as f_unsorted:
            # Create a list of offsets, each offset points to the beginning of
            # a conversation (deliniated by the sentinel)
            for line in iter(f_unsorted.readline, ''):
                if line == sentinel:
                    offsets.append(f_unsorted.tell() - len(sentinel))
            # Final offset points to the end of the file
            offsets.append(f_unsorted.tell())
            # Create a list of tuples (start, end), describing a conversation
            ranges = list(zip(offsets, offsets[1:]))
        conversations = []
        # Very important to open in binary mode
        with open(filename, 'rb') as f_unsorted:
            # Create a list of (datetime, conversation) pairs
            for r in ranges:
                f_unsorted.seek(r[0])
                conversation = bytes.decode(f_unsorted.read(r[1]-r[0]))
                date = conversation.split('\n', 3)[1]
                time = conversation.split('\n', 4)[3].split(' ', 2)[0]
                conversations.append((datetime.datetime.strptime('T'.join((date, time)), '%Y-%m-%dT%H:%M'), conversation))
        # Sort on datetime
        conversations.sort(key=itemgetter(0))

        # Write out data
        with open('{0}/{1}'.format(dest_dir, os.path.basename(filename).rstrip('.unsorted')), 'w') as f_sorted:
            for c in conversations:
                print(c[1], end='', file=f_sorted)

    print('    Conversations with {0} people stored in \'{1}\''.format(num_conversations, os.path.basename(dest_dir)), file=sys.stdout)
    print('DONE', file=sys.stdout)

# -----------------------------------------------------------------------------
def main(argv=None):
    if argv is None:
        argv = sys.argv
    parser = argparse.ArgumentParser(description='Liberate your Google Gmail chats.')
    parser.add_argument('-n', '--no-wrap', help='don\'t wrap text-formatted chats at 79 chars', action='store_true')
    parser.add_argument('-a', '--analyze', help='print a list of possible conversation thread errors', action='store_true')
    parser.add_argument('mbox', help='Gmail archive (mbox format)')
    args = parser.parse_args(args=argv[1:])

    data_dir = 'gcparse_data'
    if not os.path.isdir(data_dir):
        os.mkdir(data_dir)
    master_mbox = args.mbox
    chats_all_mbox = '{0}/chats_all.mbox'.format(data_dir)
    chats_old_mbox = '{0}/chats_old.mbox'.format(data_dir)
    chats_new_mbox = '{0}/chats_new.mbox'.format(data_dir)
    xml_dir = '{0}/xml'.format(data_dir)
    text_dir = '{0}/text'.format(data_dir)
    addresses = defaultdict(int)
    name_map = {}

    # XML
    if not os.path.isfile(chats_all_mbox):
        parse_master_mbox(master_mbox, chats_all_mbox)
    if not os.path.isfile(chats_old_mbox) and not os.path.isfile(chats_new_mbox):
        separate_old_from_new_chats(chats_all_mbox, chats_old_mbox, chats_new_mbox)
    if not os.path.isdir(xml_dir):
        os.mkdir(xml_dir)
        old_messages = parse_old_conversations(chats_old_mbox, xml_dir, addresses)
        new_messages = parse_new_conversations(chats_new_mbox, xml_dir, addresses)
        num_conversations = tag_conversations(xml_dir)
        print('{0} messages stored as {1} conversations in \'{2}\''.format(old_messages + new_messages, num_conversations, os.path.basename(xml_dir)), file=sys.stdout)
    if args.analyze:
        print('{0}'.format('*'*79), file=sys.stdout)
        find_ooo_timestamps(xml_dir)
        print('{0}'.format('*'*79), file=sys.stdout)

    # Name map
    created_name_map = False
    if not os.path.isfile('{0}/name_map'.format(data_dir)):
        # Name map doesn't exist, creat it
        for k in addresses.keys():
            name_map[k] = ''
        # My address is probably the address that appeared most frequently
        my_address = max(addresses, key=addresses.get)
        with open('{0}/name_map'.format(data_dir), 'w') as f:
            json.dump({"my_address": my_address, "all_addresses": name_map}, f, indent=4, sort_keys=True)
        created_name_map = True
    else:
        # Name map already exists, load its data
        with open('{0}/name_map'.format(data_dir), 'r') as f:
            serialized_name_map = json.load(f)
        name_map = serialized_name_map['all_addresses']
        my_address = serialized_name_map['my_address']

    # Text
    shutil.rmtree(text_dir, ignore_errors=True)
    os.mkdir(text_dir)
    format_xml_conversations_as_text(xml_dir, text_dir, my_address, name_map, args.no_wrap)
    sort_text_conversations(text_dir, text_dir)
    for filename in glob.glob('{0}/*.conv.unsorted'.format(text_dir)):
        os.remove(filename)

    if created_name_map:
        print('''
A name map has been created at \'{0}/name_map\'.

A name map allows you to replace addresses in text-formatted chats with names,
i.e. \'Aleister\' instead of \'crowley.beast666@thelema.org\'; this feature is
optional.

To use the name map, type a name in the quotes next to each address that you
want displayed as a name instead of an address, save, then re-run the program.
'''.format(data_dir), file=sys.stdout)

# -----------------------------------------------------------------------------
if __name__ == '__main__':
    sys.exit(main())
