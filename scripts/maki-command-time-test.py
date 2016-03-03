#! /usr/bin/env python

#RUN AS: rosrun maki_robot maki_command_time_test.py

import rospy
from std_msgs.msg import String
from std_srvs.srv import Empty
import os

import math
from time import sleep
import sys
import string
import signal 

from timeit import default_timer as timer	## wall clock. Unix 1/100 second granularity

import threading
from array import *
import re		# see http://stackoverflow.com/questions/5749195/how-can-i-split-and-parse-a-string-in-python
import io

## NOTE: These globals are #define at the top of the Arduino servo driver
## MAKIv1_4_servo_controller_LITE.ino
INVALID_INT = 9999
DELIMITER_RECV = ':'	## syntax for FEEDBACK delimiter
TERM_CHAR_RECV = ';'	## syntax for end of FEEDBACK
TERM_CHAR_SEND = 'Z'	## syntax for end of servo command
SC_SET_GP = "GP"	## servo command syntax for setting a specified servo's GOAL POSITION
SC_SET_GS = "GS"	## servo command syntax for setting a specified servo's GOAL SPEED
SC_SET_IPT = "IPT"	## servo command syntax for setting the INTERPOLATION POSE TIME
SC_SET_TM = "TM"  	## servo command syntax for setting a specified servo's MAX TORQUE. Note: This value exists in EEPROM and persists when power is removed; default 1023
SC_SET_TL = "TL"  	## servo command syntax for setting a specified servo's TORQUE LIMIT. Note: If set to 0 by ALARM SHUTDOWN, servo won't move until set to another value[1,1023]; default MAX TORQUE
SC_SET_TS = "TS"  	## servo command syntax for setting a specified servo's TORQUE ENABLE. Note: Boolean [0, 1]; default 1. Doesn't appear to disable servo's movement when set to 0

SC_FEEDBACK = "F"	## servo command syntax for FEEDBACK or status of all servos
SC_GET_MX = "MX"	## servo command syntax for FEEDBACK of all servo MAXIMUM POSITION
SC_GET_MN = "MN"	## servo command syntax for FEEDBACK of all servo MINIMUM POSITION
SC_GET_PP = "PP"	## servo command syntax for feedback with PRESENT POSITION
SC_GET_GP = "GP"	## servo command syntax for feedback with GOAL POSITION
SC_GET_PS = "PS"	## servo command syntax for feedback with PRESENT SPEED
SC_GET_GS = "GS"	## servo command syntax for feedback with GOAL SPEED
SC_GET_PT = "PT"	## servo command syntax for feedback with PRESENT TEMPERATURE (in Celsius)
SC_GET_PL = "PL"	## servo command syntax for feedback with PRESENT LOAD
SC_GET_TM = "TM" 	## servo command syntax for feedback with MAX TORQUE
SC_GET_TL = "TL"  	## servo command syntax for feedback with TORQUE LIMIT
SC_GET_TS = "TS"  	## servo command syntax for feedback with TORQUE ENABLE
SC_GET_ER = "ER"  	## servo command syntax for feedback with error returned from AX_ALARM_LED
SC_GET_DP = "DP"  	## servo command syntax for default positions
SC_GET_DS = "DS"  	## servo command syntax for default speed
baud_rate = 19200	#9600

## from MAKIv14.h
SERVOCOUNT = 6	## MAKIv1.4 has 6 servos
LR = 1	## EYELID_RIGHT
LL = 2	## EYELID_LEFT
EP = 3	## EYE_PAN
ET = 4	## EYE_TILT
HT = 5	## HEAD_TILT
HP = 6	## HEAD_PAN
F_VAL_SEQ = [ "LR", "LL", "EP", "ET", "HT", "HP" ]

## from MAKI-Arbotix-Interface.py
## servo control infix for type of feedback
FEEDBACK_SC = [ #SC_GET_MX,
                #SC_GET_MN,
                SC_GET_PP,
                SC_GET_GP	#,
                #SC_GET_PS,
                #SC_GET_GS,
                #SC_GET_PT,
                #SC_GET_PL,
                #SC_GET_ER,
                #SC_GET_DP,
                #SC_GET_DS,
                #SC_GET_TM,
                #SC_GET_TL,
                #SC_GET_TS
                 ]
FEEDBACK_TOPIC = [ #"maki_feedback_max_pos",
                   #     "maki_feedback_min_pos",
                        "maki_feedback_pres_pos",
                        "maki_feedback_goal_pos"	#,
                   #     "maki_feedback_pres_speed",
                   #     "maki_feedback_goal_speed",
                   #     "maki_feedback_pres_temp",
                   #     "maki_feedback_pres_load",
                   #     "maki_feedback_error",
                   #     "maki_feedback_default_pos",
                   #     "maki_feedback_default_speed",
                   #     "maki_feedback_torque_max",
                   #     "maki_feedback_torque_limit",
                   #     "maki_feedback_torque_enable"
                        ]

## More MAKI related global variables from _2015_05_14_KECK_MAKIv1_4_teleop.ino
blink_time = 75	#100	## 100ms... 75ms looks even more realistic
eyelid_offset_blinking = -50	## LL decrement position
eyelid_offset_open_wide = 30	## LL increment position

## Yet more MAKI related global variables; 2016-02-22
ht_tl_enable = 1023
ht_tl_disable = 0

#slow_blink_time = 1000
falling_asleep_time = 3000
waking_up_time = 2000
resetting_time = 2000

## ktsui, INSPIRE 4, pilot3-1
slow_blink_time = 550

## GLOBAL VARIABLES FOR PYTHON SCRIPT
VERBOSE_DEBUG = True	#False	## default is False
ARBOTIX_SIM = True
#ALIVE #= False		## make sure that all threads cleanly end
#INIT #= True		## flag to read first message from MAKI (will contain PP)
#makiPP
#makiGP

#last_blink_time = 0
#last_movement_time = 0


#####################
def parseRecvMsg ( recv_msg ):
	global makiPP, makiGP
	global init_dict
	global FEEDBACK_SC
	global VERBOSE_DEBUG
	global feedback_template
	global start_movement_time, finish_movement_time
	global expected_movement_duration

	if VERBOSE_DEBUG:
		#rospy.logdebug( "parseRecvMsg: BEGIN" )
		rospy.logdebug( "Received: " + str(recv_msg) )

	tmp = feedback_template.search(recv_msg)
	if tmp != None:
		prefix = tmp.group(1)
		feedback_values = tmp.group(2)
		#print "Validated: prefix='" + prefix + "' and feedback_values='" + feedback_values + "'"
	else:
		rospy.logerr( "Received with ERROR! Invalid message format: " + str(recv_msg) )
		return	## return without an expression argument returns None. Falling off the end of a function also returns None

	values = re.findall("([0-9]+)", feedback_values)	## this is a list of strings
	## need to conver to int (see http://stackoverflow.com/questions/22672598/converting-lists-of-digits-stored-as-strings-into-integers-python-2-7) 
	tmp_dict = dict( zip(F_VAL_SEQ, map(int, values)) )

	if prefix=="PP":	#SC_GET_PP	# present position
		if not ( tmp_dict == makiPP ):
			makiPP.update(tmp_dict)
			if VERBOSE_DEBUG: rospy.logdebug( prefix + "=" + str(makiPP) )
		if not init_dict[prefix]:
			init_dict[prefix] = True
		else:
			finish_movement_time = timer()
			rospy.logdebug( "---- finish_movement_time = " + str(finish_movement_time) )

	elif prefix=="GP":	#SC_GET_GP	# goal position
		if not ( tmp_dict == makiGP ):
			makiGP.update(tmp_dict)
			if VERBOSE_DEBUG: rospy.logdebug( prefix + "=" + str(makiGP) )
		if not init_dict[prefix]:	init_dict[prefix] = True

	else:
		rospy.logerr( "parseRecvMsg: ERROR! Unknown prefix: " + str(prefix) )
		return

	#print "parseRecvMsg: END"


#####################
def updateMAKICommand( msg ):
	global maki_command
	#rospy.logdebug(rospy.get_caller_id() + ": I heard %s", msg.data)

	## filter out feedback requests using regex
	_tmp = re.search("^F[A-Y]{2}Z$", msg.data)

	## YES, msg.data is a feedback request
	if _tmp != None:
		pass
	else:
		maki_command = msg.data 
		parseMAKICommand( maki_command )

	return

def parseMAKICommand( m_cmd ):
	global start_movement_time, finish_movement_time
	global expected_movement_duration
	global mc_count

	_emd_print = ""

	_tmp = re.search("^([A-Y]+GP[0-9]+)([A-Y]+[0-9]+)*(IPT([0-9]))*Z$", m_cmd)
	if _tmp != None:
		start_movement_time = timer()
		rospy.logdebug( "----- start_movement_time = " + str(start_movement_time) )
		if _tmp.group(4) != None:
			## convert milliseconds to float seconds
			expected_movement_duration = float(_tmp.group(4)) / 1000.0
			_emd_print = "expected_movement_duration = " + str(expected_movement_duration) 
		else:
			expected_movement_duration = None
			_emd_print = "expected_movement_duration NOT SPECIFIED" 

		mc_count += 1
		rospy.logdebug( "maki_command #" + str(mc_count) + " : " + str(m_cmd) )
		rospy.logdebug( str(_emd_print) )

#def updateStatus( ):
#	global FEEDBACK_SC
#	global ALIVE
#	_rate = 1.5	## emperically determined; 2016-02-22
#
#	while ALIVE and not rospy.is_shutdown():
#		for _servo_command in FEEDBACK_SC:
#			#print _servo_command
#			sendToMAKI( str(SC_FEEDBACK + _servo_command + TERM_CHAR_SEND) )
#			sleep(_rate)	# seconds
#	# end	while ALIVE


def sleepWhileWaiting( sleep_time, increment ):
	global PIC_INTERUPT
	global ALIVE

	if VERBOSE_DEBUG: print "BEGIN: sleepWhileWaiting for " + str(sleep_time) + " seconds"
	increment = max(1, increment)
	_start_sleep_time = timer()
	sleep(increment)	# ktsui, INSPIRE 4, pilot 2; emulate a do-while
	while ( ALIVE and
		not rospy.is_shutdown() and
		not PIC_INTERUPT and
		((timer() - _start_sleep_time) < sleep_time) ):
		sleep(increment)

	if VERBOSE_DEBUG: print "DONE: sleepWhileWaiting for " + str(sleep_time) + " seconds"

#####################
def signal_handler(signal, frame):
	global ALIVE

	ALIVE = False
	sleep(1)
	sys.exit()

#####################
def parseFeedback( msg ):
	#rospy.logdebug(rospy.get_caller_id() + ": I heard %s", msg.data)
	parseRecvMsg ( msg.data )
	return

#####################
def initROS():
	global VERBOSE_DEBUG

	## get function name for logging purposes
        _fname = sys._getframe().f_code.co_name        ## see http://stackoverflow.com/questions/5067604/determine-function-name-from-within-that-function-without-using-tracebacko
	print str(_fname) + ": BEGIN"	## THIS IS BEFORE ROSNODE INIT

	# Initialize ROS node
        # see http://wiki.ros.org/rospy/Overview/Logging
        if VERBOSE_DEBUG:
                rospy.init_node('macro_time_test', log_level=rospy.DEBUG)
		rospy.logdebug("log_level=rospy.DEBUG")
        else:
                rospy.init_node('macro_time_test')       ## defaults to log_level=rospy.INFO
	rospy.logdebug( str(_fname) + ": END")
	return

def initPubMAKI():
	global pub_cmd
	global maki_msg_format

	## get function name for logging purposes
        _fname = sys._getframe().f_code.co_name        ## see http://stackoverflow.com/questions/5067604/determine-function-name-from-within-that-function-without-using-tracebacko
	rospy.logdebug( str(_fname) + ": BEGIN")

	## make sure that commandOut ends in only one TERM_CHAR_SEND
	maki_msg_format = "\A[a-yA-Y]+[a-yA-Y0-9]*"
	maki_msg_format += str(TERM_CHAR_SEND)
	maki_msg_format += "{1}$"

	# Setup publisher
	pub_cmd = rospy.Publisher("maki_command", String, queue_size = 10)

	rospy.logdebug( str(_fname) + ": END")
	return

def initSubFeedback():
	global feedback_template

	## get function name for logging purposes
        _fname = sys._getframe().f_code.co_name        ## see http://stackoverflow.com/questions/5067604/determine-function-name-from-within-that-function-without-using-tracebacko
	rospy.logdebug( str(_fname) + ": BEGIN")

	## STEP 0: Setup regex template for expected feedback syntax
	feedback_msg_format = "\A([A-Z]{2})"	## 2 alphabetic char prefix
	feedback_msg_format += "(([0-9]+" + DELIMITER_RECV + "){" + str(SERVOCOUNT-1) + "}[0-9]+)" 
	feedback_msg_format += TERM_CHAR_RECV + "\Z"
	#print feedback_msg_format
	feedback_template = re.compile(feedback_msg_format)

	# STEP 1: Setup subscribers
	for topic in FEEDBACK_TOPIC:
		rospy.Subscriber( topic, String, parseFeedback )
		rospy.logdebug( "now subscribed to " + str(topic) )

	rospy.Subscriber( "/maki_command", String, updateMAKICommand )
	rospy.logdebug( "now subscribed to /maki_command" )

	rospy.logdebug( str(_fname) + ": END")
	return


#####################
def resetTimer():
	global start_movement_time, finish_movement_time
	global expected_movement_duration

	start_movement_time = None
	finish_movement_time = None
	expected_movement_duration = None

#####################
if __name__ == '__main__':

	global ALIVE
	global VERBOSE_DEBUG
	global INIT, init_dict
	global makiPP, makiGP
	global maki_command
	global pub_cmd
	global start_movement_time, finish_movement_time
	global expected_movement_duration
	global mc_count

	## ---------------------------------
	## INITIALIZATION
	## ---------------------------------
	## STEP 0: INIT ROS
	initROS()

	## STEP 1: INIT GLOBAL VARIABLES
	ALIVE = False
	INIT = True
	init_dict = dict( zip(FEEDBACK_SC, [ False ] * len(FEEDBACK_SC) ) )
	makiPP = dict( zip(F_VAL_SEQ, [ INVALID_INT ] * len(F_VAL_SEQ) ) )
	makiGP = dict( zip(F_VAL_SEQ, [ INVALID_INT ] * len(F_VAL_SEQ) ) )
	maki_command = ""
	mc_count = 0
	resetTimer()

	## STEP 2: SIGNAL HANDLER
	#to allow closing the program using ctrl+C
	signal.signal(signal.SIGINT, signal_handler)

	## STEP 3: INIT ROBOT STATE
	## establish communication with the robot via rostopics
	initPubMAKI()
	initSubFeedback()
	## wait here if nothing has been published to rostopics yet
	while INIT and not rospy.is_shutdown():
		my_init = INIT
		for _servo_command in FEEDBACK_SC:
			#print _servo_command
			#print my_init
			my_init = my_init and init_dict[ _servo_command ]
			#print my_init
			sleep(0.5)	#0.5s
			#sendToMAKI( str(SC_FEEDBACK + _servo_command + TERM_CHAR_SEND) )
			pub_cmd.publish( str(SC_FEEDBACK + _servo_command + TERM_CHAR_SEND) )

		if not my_init:
			sleep(1.0)
		else:
			INIT = False
			rospy.loginfo( "Init MAKI state -- DONE" )

	### STEP 4: START POLLING ROBOT FOR STATUS
	#ALIVE = True
	#thread_updateStatus = threading.Thread(target=updateStatus, args=())
	#thread_updateStatus.setDaemon(True)	# make sure to set this; otherwise, stuck with this thread open
	#thread_updateStatus.start()

	## ---------------------------------
	## END OF INITIALIZATION
	## ---------------------------------

	resetTimer()
	ALIVE = True
	while ALIVE and not rospy.is_shutdown():
		if (start_movement_time != None) and (finish_movement_time != None):
			rospy.loginfo( "maki_command #" + str(mc_count) + " : elapsed time = "
				+ str( abs(finish_movement_time - start_movement_time) ) 
				+ "; expected time = " + str(expected_movement_duration) )
			## reset
			resetTimer()

		pass	## nop to allow stdin to pass through

	#rospy.spin()	## keeps python from exiting until this node is stopped

	print "__main__: END"



