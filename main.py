import flask
from flask import render_template
from flask import request
from flask import url_for
from flask import jsonify
import uuid

import json
import logging

# Date handling 
import arrow # Replacement for datetime, based on moment.js
import datetime # But we still need time
from dateutil import tz  # For interpreting local times


# OAuth2  - Google library implementation for convenience
from oauth2client import client
import httplib2   # used in oauth2 flow

# Google API for services 
from apiclient import discovery

###
# Globals
###
import CONFIG
app = flask.Flask(__name__)

SCOPES = 'https://www.googleapis.com/auth/calendar.readonly'
CLIENT_SECRET_FILE = CONFIG.GOOGLE_LICENSE_KEY  ## You'll need this
APPLICATION_NAME = 'MeetMe class project'

#############################
#
#  Pages (routed from URLs)
#
#############################

@app.route("/")
@app.route("/index")
def index():
  app.logger.debug("Entering index")
  if 'begin_date' not in flask.session:
    init_session_values()
  return render_template('index.html')

@app.route("/choose")
def choose():
    ## We'll need authorization to list calendars 
    ## I wanted to put what follows into a function, but had
    ## to pull it back here because the redirect has to be a
    ## 'return'
    
    global gcal_service
    app.logger.debug("Checking credentials for Google calendar access")
    credentials = valid_credentials()
    if not credentials:
      app.logger.debug("Redirecting to authorization")
      return flask.redirect(flask.url_for('oauth2callback'))

    gcal_service = get_gcal_service(credentials)
    app.logger.debug("Returned from get_gcal_service")
    flask.session['calendars'] = list_calendars(gcal_service)
    return render_template('index.html')

####
#
#  Google calendar authorization:
#      Returns us to the main /choose screen after inserting
#      the calendar_service object in the session state.  May
#      redirect to OAuth server first, and may take multiple
#      trips through the oauth2 callback function.
#
#  Protocol for use ON EACH REQUEST: 
#     First, check for valid credentials
#     If we don't have valid credentials
#         Get credentials (jump to the oauth2 protocol)
#         (redirects back to /choose, this time with credentials)
#     If we do have valid credentials
#         Get the service object
#
#  The final result of successful authorization is a 'service'
#  object.  We use a 'service' object to actually retrieve data
#  from the Google services. Service objects are NOT serializable ---
#  we can't stash one in a cookie.  Instead, on each request we
#  get a fresh serivce object from our credentials, which are
#  serializable. 
#
#  Note that after authorization we always redirect to /choose;
#  If this is unsatisfactory, we'll need a session variable to use
#  as a 'continuation' or 'return address' to use instead. 
#
####

def valid_credentials():
    """
    Returns OAuth2 credentials if we have valid
    credentials in the session.  This is a 'truthy' value.
    Return None if we don't have credentials, or if they
    have expired or are otherwise invalid.  This is a 'falsy' value. 
    """
    if 'credentials' not in flask.session:
      return None

    credentials = client.OAuth2Credentials.from_json(
        flask.session['credentials'])

    if (credentials.invalid or
        credentials.access_token_expired):
      return None
    return credentials


def get_gcal_service(credentials):
  """
  We need a Google calendar 'service' object to obtain
  list of calendars, busy times, etc.  This requires
  authorization. If authorization is already in effect,
  we'll just return with the authorization. Otherwise,
  control flow will be interrupted by authorization, and we'll
  end up redirected back to /choose *without a service object*.
  Then the second call will succeed without additional authorization.
  """
  app.logger.debug("Entering get_gcal_service")
  http_auth = credentials.authorize(httplib2.Http())
  service = discovery.build('calendar', 'v3', http=http_auth)
  app.logger.debug("Returning service")
  return service

@app.route('/oauth2callback')
def oauth2callback():
  """
  The 'flow' has this one place to call back to.  We'll enter here
  more than once as steps in the flow are completed, and need to keep
  track of how far we've gotten. The first time we'll do the first
  step, the second time we'll skip the first step and do the second,
  and so on.
  """
  app.logger.debug("Entering oauth2callback")
  flow =  client.flow_from_clientsecrets(
      CLIENT_SECRET_FILE,
      scope= SCOPES,
      redirect_uri=flask.url_for('oauth2callback', _external=True))
  ## Note we are *not* redirecting above.  We are noting *where*
  ## we will redirect to, which is this function. 
  
  ## The *second* time we enter here, it's a callback 
  ## with 'code' set in the URL parameter.  If we don't
  ## see that, it must be the first time through, so we
  ## need to do step 1. 
  app.logger.debug("Got flow")
  if 'code' not in flask.request.args:
    app.logger.debug("Code not in flask.request.args")
    auth_uri = flow.step1_get_authorize_url()
    return flask.redirect(auth_uri)
    ## This will redirect back here, but the second time through
    ## we'll have the 'code' parameter set
  else:
    ## It's the second time through ... we can tell because
    ## we got the 'code' argument in the URL.
    app.logger.debug("Code was in flask.request.args")
    auth_code = flask.request.args.get('code')
    credentials = flow.step2_exchange(auth_code)
    flask.session['credentials'] = credentials.to_json()
    ## Now I can build the service and execute the query,
    ## but for the moment I'll just log it and go back to
    ## the main screen
    app.logger.debug("Got credentials")
    return flask.redirect(flask.url_for('choose'))

#####
#
#  Option setting:  Buttons or forms that add some
#     information into session state.  Don't do the
#     computation here; use of the information might
#     depend on what other information we have.
#   Setting an option sends us back to the main display
#      page, where we may put the new information to use. 
#
#####

@app.route('/setrange', methods=['POST'])
def setrange():
    """
    User chose a date range with the bootstrap daterange
    widget.
    """
    app.logger.debug("Entering setrange")
    flask.flash("Setrange gave us '{}' for the date".format(
      request.form.get('daterange')))
    daterange = request.form.get('daterange')
    flask.session['daterange'] = daterange
    daterange_parts = daterange.split()
    flask.session['begin_date'] = interpret_date(daterange_parts[0])
    flask.session['end_date'] = interpret_date(daterange_parts[2])
    flask.flash("Setrange gave us '{}' and '{}' as beginning and ending times, respectively".format(
        request.form.get('begin_time'), request.form.get('end_time')))
    flask.session['begin_time'] = interpret_time(request.form.get('begin_time'))
    flask.session['end_time'] = interpret_time(request.form.get('end_time'))
    print(flask.session['end_time'].format("HH:mm"))
    app.logger.debug("Setrange parsed {} - {}  dates as {} - {} times as {} - {}".format( daterange_parts[0], daterange_parts[1],
                flask.session['begin_date'], flask.session['end_date'],
                flask.session['begin_time'], flask.session['end_time']))
    return flask.redirect(flask.url_for("choose"))

@app.route('/selected', methods=['POST'])
def fetchcal():
    """
    A function that create a list of selected calendars.
    """
    app.logger.debug("Fetching the calendar(s) selected")
    cals = []
    selected = request.form.getlist('calendar')
    app.logger.debug(selected)
    for cal in flask.session['calendars']:
        if cal['id'] in selected:
            cals.append(cal)
    app.logger.debug(cals)
    find_busy_free(cals)
    return flask.redirect("/index")

####
#
#   Initialize session variables 
#
####

def init_session_values():
    """
    Start with some reasonable defaults for date and time ranges.
    Note this must be run in app context ... can't call from main. 
    """
    # Default date span = tomorrow to 1 week from now
    now = arrow.now('local')
    tomorrow = now.replace(days=+1)
    nextweek = now.replace(days=+7)
    flask.session["begin_date"] = tomorrow.floor('day').isoformat()
    flask.session["end_date"] = nextweek.ceil('day').isoformat()
    flask.session["daterange"] = "{} - {}".format(
        tomorrow.format("MM/DD/YYYY"),
        nextweek.format("MM/DD/YYYY"))
    # Default time span each day, 8 to 5
    flask.session["begin_time"] = interpret_time("9am")
    flask.session["end_time"] = interpret_time("5pm")

def interpret_time( text ):
    """
    Read time in a human-compatible format and
    interpret as ISO format with local timezone.
    May throw exception if time can't be interpreted. In that
    case it will also flash a message explaining accepted formats.
    """
    app.logger.debug("Decoding time '{}'".format(text))
    time_formats = ["ha", "h:mma",  "h:mm a", "H:mm"]
    try: 
        as_arrow = arrow.get(text, time_formats).replace(tzinfo=tz.tzlocal())
        app.logger.debug("Succeeded interpreting time")
    except:
        app.logger.debug("Failed to interpret time")
        flask.flash("Time '{}' didn't match accepted formats 13:30 or 1:30pm"
              .format(text))
        raise
    return as_arrow.isoformat()

def interpret_date( text ):
    """
    Convert text of date to ISO format used internally,
    with the local time zone.
    """
    try:
      as_arrow = arrow.get(text, "MM/DD/YYYY").replace(
          tzinfo=tz.tzlocal())
    except:
        flask.flash("Date '{}' didn't fit expected format 12/31/2001")
        raise
    return as_arrow.isoformat()

def next_day(isotext):
    """
    ISO date + 1 day (used in query to Google calendar)
    """
    as_arrow = arrow.get(isotext)
    return as_arrow.replace(days=+1).isoformat()

####
#
#  Functions (NOT pages) that return some information
#
####
  
def list_calendars(service):
    """
    Given a google 'service' object, return a list of
    calendars.  Each calendar is represented by a dict, so that
    it can be stored in the session object and converted to
    json for cookies. The returned list is sorted to have
    the primary calendar first, and selected (that is, displayed in
    Google Calendars web app) calendars before unselected calendars.
    """
    app.logger.debug("Entering list_calendars")  
    calendar_list = service.calendarList().list().execute()["items"]
    result = [ ]
    for cal in calendar_list:
        kind = cal["kind"]
        id = cal["id"]
        if "description" in cal: 
            desc = cal["description"]
        else:
            desc = "(no description)"
        summary = cal["summary"]
        # Optional binary attributes with False as default
        selected = ("selected" in cal) and cal["selected"]
        primary = ("primary" in cal) and cal["primary"]
        

        result.append(
          { "kind": kind,
            "id": id,
            "summary": summary,
            "selected": selected,
            "primary": primary
            })
    return sorted(result, key=cal_sort_key)


def cal_sort_key( cal ):
    """
    Sort key for the list of calendars:  primary calendar first,
    then other selected calendars, then unselected calendars.
    (" " sorts before "X", and tuples are compared piecewise)
    """
    if cal["selected"]:
       selected_key = " "
    else:
       selected_key = "X"
    if cal["primary"]:
       primary_key = " "
    else:
       primary_key = "X"
    return (primary_key, selected_key, cal["summary"])

def find_busy_free(cal_list):
    """
    A function that goes through a list of calendars and pulls all busy times from them.
    """
    busy_times = []
    begin = flask.session['begin_date']
    end = flask.session['end_date']
    begin_time = flask.session['begin_time']
    end_time = flask.session['end_time']
    
    #To split into days
    end = next_day(end)
    
    #Format to datetime
    begin = begin.format('YYYY-MM-DD HH:mm:ss ZZ')
    end = end.format('YYYY-MM-DD HH:mm:ss ZZ')
    
    #To go through each selected calendar and pull the busy times using freebusy
    app.logger.debug(cal_list)
    for cal in cal_list:
        _id = cal['id']
        
        #The query for each of the calenders selected
        freebusy_query = {"timeMin": begin,
                            "timeMax": end,
                            "items": [{"id": _id}]}
    
        result = gcal_service.freebusy().query(body=freebusy_query).execute()

        #Gets the busy times from the result and adds them to an overall list
        busy_time = result['calendars'][_id]['busy']
        busy_times.append(busy_time)

    #Puts all events into the same list
    ev_list = []
    
    for i in range(len(busy_times)):
        ev_list.extend(busy_times[i])

    ev_list = sort_times(ev_list)
    ev_list = consolidate_events(ev_list)
    app.logger.debug(ev_list)

    ret_busy = []

    #Finds the overlap between each busy time and time range
    for times in ev_list:
        busy_start = times['start']
        busy_end = times['end']
        
        if (busy_start < begin_time and busy_end <= begin_time):
            ret_busy.append({'start': busy_start, 'end': busy_end})
            
        elif (end_time <= busy_start and end_time < busy_end):
            ret_busy.append({'start': busy_start, 'end': busy_end})
            
        else:
            break

    #Prints busy times
    app.logger.debug(ret_busy)
    if ret_busy != []:
        flask.flash("These busy times were found:")
        for busy_time in ret_busy:
            b_start = arrow.get(busy_time['start']).to('local').format("MM/DD/YYYY HH:mm A")
            b_end = arrow.get(busy_time['end']).to('local').format("HH:mm A")
            
            message = "Busy from {} to {}".format(b_start,b_end)
            flask.flash(message)
    else:
        flask.flash("No busy times found")

    flask.flash("")
    ret_free = free_time(ret_busy)
    app.logger.debug(ret_free)
    if ret_free != []:
        flask.flash("These free times were found:")
        for fr_time in ret_free:
            f_start = arrow.get(fr_time['start']).to('local').format("MM/DD/YYYY HH:mm A")
            f_end = arrow.get(fr_time['end']).to('local').format("HH:mm A")
            
            message = "Free from {} to {}".format(f_start,f_end)
            flask.flash(message)
    else:
        flask.flash("No free times found")


def sort_times(ev_list):
    """
    Sorts a list of event by the start times across multiple calenders for ease of display and operation
    """
    start_times = []
    for ev in ev_list:
        start_times.append(ev['start'])
    start_times.sort()

    sorted = []
    for st_time in start_times:
        for ev in ev_list:
            ev_start = ev['start']
            ev_end = ev['end']
            if st_time == ev_start:
                sorted.append({'start': ev_start, 'end':ev_end})

    return sorted

def free_time(busy_list):
    """
    Finds the free times from a list of busy
    """

    free_times = []
    runover = []
    
    #Constructs the starting and ending points for each day
    str_date = arrow.get(flask.session['begin_date'])
    str_hour = arrow.get(flask.session['begin_time']).hour
    str_min = arrow.get(flask.session['begin_time']).minute
    start = str_date.replace(hour=str_hour, minute=str_min)
    app.logger.debug(start)
    
    end_date = arrow.get(flask.session['end_date'])
    end_hour = arrow.get(flask.session['end_time']).hour
    end_min = arrow.get(flask.session['end_time']).minute
    end = end_date.replace(hour=end_hour, minute=end_min)
    app.logger.debug(end)
    
    #Tests to see if there is a free period before the first event, if so appends
    first_ev = busy_list[0]
    if arrow.get(first_ev['start']) > start:
        free_times.append({'start': start, 'end': first_ev['start']})
    
    print("Starting for loop")
    for i in range(len(busy_list)-1):
        ev = busy_list[i]
        next = busy_list[i+1]
        
        ev_end = arrow.get(ev['end'])
        next_start = arrow.get(next['start'])
        end_day = ev_end.day
        st_day = next_start.day
        #Determines if there is a space between the event's end and the next's start
        if ev_end < next_start:
            if ev_end.day == next_start.day:
                free_times.append({'start': ev['end'], 'end':next['start']})
            #Fixes the runover to fit in the legal time frame
            else:
                free_times.append({'start': ev_end, 'end': end.replace(day=end_day)})
                if next_start > start.replace(day=st_day):
                    free_times.append({'start': start.replace(day=st_day), 'end': next_start})
    
    #Finds the last free periods after the last event
    last_ev = busy_list[len(busy_list)-1]
    if arrow.get(last_ev['end']) < end:
        free_times.append({'start': last_ev['end'], 'end': end})

    app.logger.debug(free_times)
    return free_times

def consolidate_events(ev_list):
    """
    Consolidates the busy times of multiple calenders so there is no overlap in busy events
    """
    consolidated = []
    for i in range(len(ev_list)-1):
        ev = ev_list[i]
        next = ev_list[i+1]
        
        #If the next busy event starts before the current event ends and ends before the current event does.
        if (ev['end'] > next['start'] and ev['end'] > next['end']):
            consolidated.append({'start': ev['start'], 'end': ev['end']})
            ev_list[i+1]['end'] = ev['end']

        #If the next busy event starts before the event ends
        elif ev['end'] > next['start']:
            consolidated.append({'start': ev['start'], 'end': next['start']})

        else:
            consolidated.append({'start': ev['start'], 'end': ev['end']})

    #Adds the final event
    consolidated.append(ev_list[len(ev_list)-1])

    return consolidated

#################
#
# Functions used within the templates
#
#################

@app.template_filter( 'fmtdate' )
def format_arrow_date( date ):
    try: 
        normal = arrow.get( date )
        return normal.format("ddd MM/DD/YYYY")
    except:
        return "(bad date)"

@app.template_filter( 'fmttime' )
def format_arrow_time( time ):
    try:
        normal = arrow.get( time )
        return normal.format("HH:mm")
    except:
        return "(bad time)"
    
#############


if __name__ == "__main__":
  # App is created above so that it will
  # exist whether this is 'main' or not
  # (e.g., if we are running in a CGI script)

  app.secret_key = str(uuid.uuid4())  
  app.debug=CONFIG.DEBUG
  app.logger.setLevel(logging.DEBUG)
  # We run on localhost only if debugging,
  # otherwise accessible to world
  if CONFIG.DEBUG:
    # Reachable only from the same computer
    app.run(port=CONFIG.PORT)
  else:
    # Reachable from anywhere 
    app.run(port=CONFIG.PORT,host="0.0.0.0")
    
