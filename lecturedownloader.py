"""Downloads all files in register.json with a valid download link."""
import json                       # Parses register.json
import signal                     # Captures SIGINT to halt after current download completes
import getpass                    # Used for importing password
import sys                        # Exits after force quit
import re                         # Parses filenames
import os                         # Makes directories
import requests                   # Downloads and authenticates
from clint.textui import progress # Used for dynamic progress bars

# JSON Register Data Structure
#   [
#       {
#           courseName
#           courseCode
#           numOfLectures
#           courselectures[
#               {
#                   'presenter'
#                   'date'
#                   'time'
#                   'length'
#                   'link'
#                   'notes'
#               }
#           ]
#       }
#   ]

__REGISTER = 'register.json'
__HALT = False
__NUMLECTURESDOWNLOADED = 0
# Authenticated web-session
__SESH = None # Defined by login()

def main():
    """Downloads lectures that haven't been downloaded yet."""
    # session object, used to authenticate, then download lectures
    global __SESH

    # Load file register
    print "Loading file register '%s'..." %__REGISTER
    register = load_register()
    if not register:
        # If __REGISTER file doesn't exist
        print "Failed to load register file.\n"\
            "Run 'scrapy runspider lectureScraper.py' first to generate '%s'" %(__REGISTER)
        return

    print "Login to MyMedia to download lectures."
    # If log in failed quit the program

    loggedin = login()
    if not loggedin:
        __SESH.close()
        return

    begin = raw_input('Begin downloading lectures (y/n): ').lower()
    if begin == 'y':
        # Searches through file register, and downloads missing files
        download_lectures(register)
        # Saves updated register to file
        save_register(register)
        print '%s lecture%s downloaded.'\
            %(__NUMLECTURESDOWNLOADED, 's' if __NUMLECTURESDOWNLOADED > 1 else '')
    else:
        print "Quitting."

    __SESH.close()
    return

def download_lectures(register):
    """Searches & downloads files in the register that haven't been downloaded yet."""
    global __NUMLECTURESDOWNLOADED

    # Iterate through each course dictionary in register
    for course_indx in xrange(len(register)):
        coursemeta = {
            key:register[course_indx][key] for key in ('courseName', 'courseCode', 'numOfLectures')
        }
        lectures = register[course_indx]['courselectures']

        # Iterate through each recording session for this course
        for session_indx in xrange(len(lectures)):
            lecture = lectures[session_indx]

            if not __HALT:
                # If the lecture contains a valid link and it hasn't been downloaded yet
                if lecture['link'] and not lecture['file']:
                    # Download Lecture
                    print 'Downloading ' + coursemeta['courseName'] + \
                          ' lecture from ' + lecture['date'] + ' ' + lecture['time']

                    # Get directory path and make folders to download lecture to
                    directory = dir_structure(coursemeta, lecture)

                    # Download lecture into directory
                    lecturepath = download_file(lecture['link'], directory)

                    # Add lecture filename and path to the register
                    # Indicates the lecture has now been downloaded
                    lecture['file'] = lecturepath

                    __NUMLECTURESDOWNLOADED = __NUMLECTURESDOWNLOADED + 1

            else:
                return

def download_file(url, directory='.'):
    """Downloads a file in chunks."""
    # Adapted from:
    # stackoverflow.com/questions/16694907/how-to-download-large-file-in-python-with-requests-py
    global __SESH

    # Combine date and name to get unique name for each lecture
    local_filename = url.split('/')[-3] + ' ' + url.split('/')[-1]
    relative_path = directory + '/' + local_filename

    # stream=True parameter ensures page is streamed to reduce memory usage
    req = __SESH.get(url, stream=True)

    total_size = int(req.headers.get('content-length', 0))

    with open(relative_path, 'wb') as fyle:
        for chunk in progress.bar(
                req.iter_content(chunk_size=1024), expected_size=(total_size/1024) + 1):
            if chunk: # filter out keep-alive new chunks
                fyle.write(chunk)
    return relative_path

def dir_structure(coursemeta, lecture):
    """Creates directory for a lecture if it doesn't already exist.
        returns - string containing path to download directory"""

    # Base directory containing all lectures
    base_dir = 'lectures'

    # Get Month and Year for this lecture
    directory = [base_dir]
    _ = re.search(r'\d\d/(\d\d)/(\d\d)', lecture['date']).groups()

    month = int(_[0]) # Month
    directory.append('20' + _[1]) # Year

    if month >= 1 and month <= 6:
        # Semester 1
        directory.append('semester1')
    elif month >= 7 and month <= 12:
        # Semester 2
        directory.append('semester2')
    else:
        # Else date can't be determined - must be manually sorted
        directory.append('ERROR')

    # Shorten course names for use as directory names
    short_coursename = re.sub(r' +', ' ', coursemeta['courseName'])
    short_coursename = re.sub(
        r' ?[^a-zA-Z0-9\(\) &]'\
        r'| ?UG & PG'\
        r'| ?Combined'\
        r'| ?\(.*\)',
        '',
        short_coursename
    )
    directory.append(short_coursename)

    # Insert '/' into directory list
    directory = '/'.join(directory)

    if not os.path.exists(directory):
        os.makedirs(directory)

    return directory

def login():
    """Logs into MyMedia and authenticates for all future downloads."""
    global __SESH

    def check_login(content):
        """Check login page for success text."""
        return 'Log In Successful' in content

    loginpage_url = 'https://login.adelaide.edu.au'

    # Load Login page
    __SESH = requests.Session()
    resp = __SESH.get(loginpage_url)

    # Scrape CSRF token and execute code
    csrf_token = re.search(r'name="lt".*value="(.*)"', resp.content).group(1)
    execute = re.search(r'name="execution".*value="(.*)"', resp.content).group(1)

    auth_url = loginpage_url + r'/cas/login?service=https%3A%2F%2Fmymedia.adelaide.edu.au%2F'

    max_tries = 3
    for attempt in range(max_tries):
        # Fill in payload data to be POSTED
        payload = {
            'username': raw_input('    Username: '),
            'password': getpass.getpass('    Password: '),
            'lt': csrf_token,
            'execution': execute,
            '_eventId': 'submit',
            'submit': 'Login'
        }

        # POST to login
        resp = __SESH.post(auth_url, data=payload)
        # Check if redirected to login success page
        if check_login(resp.text):
            # Login successful
            print 'Login Success!'
            return True
        else:
            # Authentication Failed
            if attempt < max_tries-1:
                # At least 1 attempt remaining
                rmg = max_tries-(attempt+1)
                print 'Login Failed - %d attempt%s remaining'\
                    %(rmg, 's' if rmg > 1 else '')
            else:
                # All attempts used
                print 'Login Failed - Exiting.'
                return False

def load_register():
    """Returns lecture register file."""
    try:
        # Open register json file
        reg_file = open(__REGISTER, 'r')
    except IOError:
        # If it doesn't exist - first time running, return empty dict
        return dict()
    # Else return the JSON dictionary object
    register = json.load(reg_file)
    reg_file.close()
    return register

def save_register(register):
    """Writes whole register data to file."""
    # Open register json file
    reg_file = open(__REGISTER, 'w')
    json.dump(register, reg_file)
    reg_file.close()
    return

def sigint_handler(passedsignal, frame):
    """Captures SIGINT signal to terminate downloader inbetween downloads gracefully."""
    global __HALT

    if not __HALT:
        # ^C pressed once
        __HALT = True
        print "\nHalting. Program will terminate after current download finishes."
        print "Press ^C again to force quit - This may corrupt any currently open files!"
    else:
        # ^C pressed twice, force quitting
        print "\nQuitting..."
        sys.exit(1)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, sigint_handler)
    main()
