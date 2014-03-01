# gcparse

Liberate your Google Gmail chats

## Requirements 

+ Python 3
+ [lxml](http://lxml.de)

I tried to write this in Python 2.x but it wasn't up to the task. (Hey, an
actual reason to use Python 3!) I also tried hard to avoid external
dependencies but gave up due to shortcomings in the standard library.

## About

`gcparse` frees your Gmail chat/instant message history from Google. It
produces a nicely-formatted plain text record of your chats, organized by
person: one file for each person you've chatted with. It also makes
XML-formatted conversations, if you're into that sort of thing.

To use `gcparse`, you have to feed it an mbox file from a Google Mail
"archive". To create your mail archive, log in to any Google service and
click through *Account/Data tools/select data to download/Create an archive*.

`gcparse` *only* writes into its data directory `gcparse_data` which it
creates next to itself. It's always okay to delete the entire data directory
and start over.

### Name map

Google chat identifies people by their addresses, so without modification a
chat line will look something like this:

    23:59  crowley.beast666@thelema.org: Do as thou wilt.

The optional name map can turn that line into:

    23:59  Aleister: Do as thou wilt.

Much nicer, right?

`gcparse` creates an empty name map the first time it runs, it's called
`name_map` and you can find it in the data directory.

You have to fill in the names yourself. It's easy, just type the name you
want to use next to the address you want to map and save the file.

You can use the name map for select addresses only — empty names will be
displayed as addresses. You can also map different addresses to the same
name and `gcparse` will do the right thing.

One other point: `my_address` in the name map is a required field. `gcparse`
should be able to guess your address, but if text-formatted chats come out
in funny places you should check that `my_address` really is your address.
If it's wrong, no problem, just fix it and re-run.

### `-n, --no-wrap` option

By default, individual chat messages that span multiple lines will have their
line breaks recalculated when formatted for text. To preserve line breaks,
use this option. There are only two reasons to consider using it: If you have
a lot of *pre-formatted* *multi-line* messages, or if you chat with
people with very long names. The default should be fine for just about
everyone.

### `-a, --analyze` option

If you want to manually fix conversation threading errors (see discussion
below), this option helpfully prints a list of out-of-order timestamps which
are very good proxies for type III threading errors.

## Limitations

#### Group chat
Group chat isn't supported.

#### Time
Text-formatted chats use military time adjusted for the timezone your
computer thinks it's in when you run `gcparse`. If at some point you chatted
from a different timezone, the text-formatted time will be wrong. There's no
way around this other than manually editing the timestamps because there
isn't any geo data in the archive file to match time to place.

Old-style XML chats use Unix time with milliseconds, but milliseconds aren't
preserved in new-style chat messages (in use since about May 2013). For
new-style messages, `gcparse` writes fake milliseconds starting at zero in
order to preserve message sequence. 

#### Conversation threading
Google organizes messages into conversations using thread IDs. Most of the
time the messages collected into one THRID are an accurate representation of
what a human would think of as one conversation, but there are three types of
failures that sometimes occur: Multiple
conversations can be incorrectly grouped into one THRID; single conversations
can be split across multiple THRIDs; worst of all, non-contiguous lines from
a single conversation can be sharded out into different THRIDs, garbling parts
of a conversation completely (type III). None of these problems can be solved
automatically. Fortunately, THRID errors seem to be infrequent. In my personal
corpus of 2654 conversations, there are 9 THRID errors (0.3%), 6 of which
are type III. 

## A few words on Google and your data

Google pays lip service to your data being yours, but their hearts don't seem
to be in it.

For example, there's currently a very bad bug with Google's archive files.
**The archives are incomplete.** I reported the bug on February 2, 2014:

> Using the Accounts web interface, I downloaded an achive of all my gmail
> messages ('Include all of your mail'), and there are missing messages. For
> example, in the archive xxxxxxxx@gmail.com-20140202T201547Z-Mail.zip, the
> message with Message-ID: xxxxxxx.xxxxxxxxxxxxxxxxxx.chat@gmail.com is
> missing.

In my case, 74 chat messages are missing out of a total of 5361
(1.4%). I haven't checked if the same problem exists for mail messages.

Another example: have you looked at your recent Google chats in Apple Mail?
Each line you or your buddy typed is a separate message, and there's no way
to connect the messages into conversations because apparently Google strips
the threading headers (X-GM-THRID and X-Gmail-Labels) from chat messages
received via IMAP.

It also seems that Google prevents users from accessing any chat headers at
all in the Gmail web UI (headers can be shown for regular emails using the
*show original* command). But don't worry, you can still *view* threaded
conversations in that poor and worsening web interface.

It wasn't always like this — chats were neatly threaded before about May 2013.

For now, critical headers aren't stripped from "archive" data.

###### No copyright, ninetythirty, February 2014.
