"""Scrapes MyMedia using Scrapy 1.4.0 and Selenium WebDriver to generate register.json.
    usage: scrapy runspider lectureScraper.py
    requires: selenium webdriver, scrapy 1.4.0, phantomjs"""

import types
import json
import re
import getpass
import logging
import scrapy
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait # available since 2.4.0
from selenium.webdriver.support import expected_conditions as EC # available since 2.26.0
from selenium.common.exceptions import TimeoutException # Timeout exception for WebDriverWait
from selenium.webdriver.remote.remote_connection import LOGGER as SELENIUM_LOGGER


class LectureSpider(scrapy.Spider):
    """Class implements lecture metadata scraper, and download manager."""

    name = "LectureSpider"
    custom_settings = {
        # 'DOWNLOADER_MIDDLEWARES': {'lectureScraper.SeleniumMiddleware': 200},
        # 'DUPEFILTER_DEBUG' : True,
        # 'COOKIES_DEBUG': True
        }
    start_urls = ["https://login.adelaide.edu.au/cas/login"]

    def __init__(self):
        # Suppresses log info from selenium below warning level
        SELENIUM_LOGGER.setLevel(logging.WARNING)
        self.browser = 'phantomjs'

        if self.browser == 'firefox':
            self.driver = webdriver.Firefox()
        else:
            self.driver = webdriver.PhantomJS()

        self.logger.info('Using %s browser for Selenium.' % self.browser)

    def parse(self, response):
        """Default callback function for scrapy."""

        # Login to MyMedia
        max_tries = 3
        for attempt in range(max_tries):
            if not self.auth():
                # Authentication Failed
                if attempt >= max_tries-1:
                    self.logger.error('Login Failed - Exiting.')
                    return
                else:
                    rmg = max_tries-(attempt+1)
                    self.logger.warning('Login Failed - %d attempt%s remaining'
                                        %(rmg, 's' if rmg > 1 else ''))
            else:
                self.logger.info("Login Succeeded.")
                break

        # Authentication Succeeded, continue...
        self.driver.get("https://mymedia.adelaide.edu.au/user/bb_courses")
        self.show_subject_tables()
        return self.scrape_subject_tables()

    def auth(self):
        """Logs into webpage."""

        # Selenium requests login page
        self.driver.get(self.start_urls[0])

        # Finds login elements
        username_sel = self.driver.find_element_by_id("username")
        password_sel = self.driver.find_element_by_name("password")

        # Asks for username/password
        usr = raw_input('Username: ')
        pwd = getpass.getpass()

        # Input credentials and click submit
        username_sel.send_keys(usr)
        password_sel.send_keys(pwd)
        self.driver.find_element_by_xpath("//input[@name='submit']").click()

        return self.check_login()

    def check_login(self):
        """Check if login successful."""

        if "Log In Successful" not in self.driver.page_source:
            # Report login failure and terminate
            return False

        # Otherwise login Success!
        return True

    def show_subject_tables(self):
        """Requests subject table information."""
        # Select course headings
        arrows = self.driver.find_elements_by_xpath('//div[@class="my_courses_course_section"]/a')
        num_courses = len(arrows)
        self.logger.info(str(num_courses)+' courses found.')

        # Click arrow next to headings to load tables
        for arrow in arrows:
            arrow.click()

        # Wait for all tables to finish loading - times-out after 10s
        timeout = False
        for i in range(num_courses):
            self.logger.info('Requesting course metadata. (%d/%d)' %(i+1, num_courses))
            try:
                table_sel = (
                    By.XPATH,
                    '//div[@class="my_courses_sessions_section"][' + str(i+1) + ']/table'
                )
                WebDriverWait(self.driver, 15).until(EC.presence_of_element_located(table_sel))
            except TimeoutException:
                timeout = True
                self.logger.warning("Time-out waiting for table to load.")
            else:
                timeout = timeout or False

        if not timeout:
            self.logger.info("All tables loaded.")
        else:
            self.logger.warning("Some tables not loaded.")

        return

    def scrape_subject_tables(self):
        """Scrapes lecture information from subject tables."""

        # Grab page html from selenium
        page_content = self.page_html()
        # Load register to check what values already exist
        old_reg = load_register()

        # Select all tables in scrapy
        for course_sel in page_content.xpath('//div[@class="my_courses_sessions_section"]'):

            # Collect Course Metadata
            coursemeta_sel = course_sel.xpath(
                './preceding-sibling::div[@class="my_courses_course_section"][1]')
            meta_coursename = ex_first(coursemeta_sel.xpath('./b/a/text()'))
            meta_coursecode = ex_first(coursemeta_sel.xpath('./span/i/text()'))
            # numsessions given as string '(x sessions)' must extract x using re
            _ = ex_first(coursemeta_sel.xpath('./i/text()'))
            meta_numsessions = int(re.sub('[^0-9]+', '', _))

            # Search current register for this course. Store course info in old_course if it exists
            courselectures_reg = search_dicts(
                old_reg, 'courseName', meta_coursename
            )[0]['courselectures']

            # Iterate through course sessions & scrape session metadata
            data_courselectures = list()
            for session_sel in course_sel.xpath('./table/tbody/tr'):
                # Scrape lecture data and append to list of lectures for this course
                data_courselectures.append(self.scrape_sessiondata(session_sel, courselectures_reg))

            # Returns Course metadata as dictionary containing metadata & list of lecture data dicts
            yield {                                     # COURSE {
                'courseName': meta_coursename,          #   metadata
                'courseCode': meta_coursecode,          #
                'numOfLectures': meta_numsessions,      #
                'courseLectures' : data_courselectures  #   LECTURES [lecture0 {},lecture1 {}, ...]
            }                                           # }

    def scrape_sessiondata(self, session_sel, courselectures_reg):
        """Scrapes data for a single recording session."""

        # Scrape session data from table row
        presenter = ex_first(session_sel.xpath('./td[2]/a/text()'))
        datetime = ex_first(session_sel.xpath('./td[3]/a/text()'))
        date = re.search(r'\d+/\d+/\d+', datetime).group(0)
        time = re.search(r'\d+\:\d+ [a-zA-Z]+', datetime).group(0)
        # Duration has extraneous \n and spaces to be removed using re
        duration = ex_first(session_sel.xpath('./td[4]/text()'))
        duration = re.sub(r'[^0-9\:]+', '', duration)
        # Notes are stored in two potential locations & need to be concatenated if they exist
        notes = session_sel.xpath(
            './td[5]/text() | ./td[5]/span/span[@class="more_text"]/text()'
        ).extract()

        # Search course register to see if a lecture at this date, time, duration already exists
        lecture_reg = search_dicts(
            courselectures_reg, ['date', 'time', 'length'], [date, time, duration]
        )

        # Check if this lecture already exists in the register
        if not lecture_reg:
            # New session has been found - Scrape download link from lecture page
            # downloadlink = ''
            downloadlink = self.scrape_downloadlink(ex_first(session_sel.xpath('./td[1]/a/@href')))
            # Session doesn't exist, so file has yet to be downloaded
            filepath = ''
        else:
            # Session already exists in register, re-use old information
            downloadlink = lecture_reg[0]['link']
            filepath = lecture_reg[0]['file']

        # return dictionary containing session data
        return {
            'link': downloadlink,
            'presenter': presenter,
            'date': date,
            'time': time,
            'length': duration,
            'notes': ''.join(notes),
            'file': filepath
        }



    def scrape_downloadlink(self, pagelink):
        """Follows url in new tab and scrapes download link."""
        # Follow link to lecture page
        self.driver.get(pagelink)

        # Parse page and grab MP4 Download link with Scrapy
        content = self.page_html()
        return ex_first(
            content.xpath(
                './/div[@id="files_for_session"]/table/tbody'\
                '/tr[td/text()="MP4"]/td[3]/a/@href'
            )
        )

    def page_html(self):
        """Return Scrapy HtmlResponse containing page content from selenium."""
        return scrapy.http.HtmlResponse(
            url=self.driver.current_url,
            body=self.driver.page_source,
            encoding='utf-8'
        )

def load_register():
    """Returns lecture register file."""
    try:
        # Open register json file
        reg_file = open('register.json', 'r')
    except IOError:
        # If it doesn't exist - first time running, return empty dict
        return dict()
    # Else return the JSON dictionary object
    register = json.load(reg_file)
    reg_file.close()
    return register

def ex_first(selector):
    """Returns string for first object found at selector."""
    lst = selector.extract()
    return lst[0] if lst else ''

def search_dicts(lst, keys, values):
    """Searches a list of dictionaries for a given set of key/value pairs.

        returns - first dictionary that matches {key: value}
                  None if it doesn't find any."""

    def search_key(lst, key, value):
        """Searches a list of dictionaries for a given key/value pair"""
        try:
            return [item for item in lst if item[key] == value]
        except KeyError:
            return []

    if not isinstance(keys, (types.ListType, types.TupleType)):
        keys = [keys]

    if not isinstance(values, (types.ListType, types.TupleType)):
        values = [values]

    for pair in zip(keys, values):
        # print pair
        lst = search_key(lst, pair[0], pair[1])

    return lst
