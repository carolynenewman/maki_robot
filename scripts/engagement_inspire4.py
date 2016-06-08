#! /usr/bin/env python

import rospy
from std_msgs.msg import String
import os

import math
import string
import random
import thread

from maki_robot_common import *
from dynamixel_conversions import dynamixelConversions
from base_behavior import *	## baseBehavior, headTiltBaseBehavior, eyelidBaseBehavior, eyelidHeadTiltBaseBehavior
from ROS_sleepWhileWaiting import ROS_sleepWhileWaiting_withInterrupt

HT_STARTLE = 525

########################
## Infant engagement behaviors for INSPIRE4 study
##
## STARTLE
## Description: from neutral, MAKI rapidly opens eyes wide (LL_OPEN_MAX)
##	and head lifts slightly (HT). 
##
## TODO:
##	* Eye tilt (ET) compensates for HT
########################
class engagementStartleGame( eyelidHeadTiltBaseBehavior ):	#headTiltBaseBehavior, eyelidBaseBehavior ):
	## variables private to this class
	## all instances of this class share the same value
	__is_startled = None
	__is_game_running = None
	__is_game_exit = None


	def __init__(self, verbose_debug, ros_pub):
		## call base class' __init__
		eyelidHeadTiltBaseBehavior.__init__( self, verbose_debug, ros_pub )

		## add anything else needed by an instance of this subclass
		if engagementStartleGame.__is_startled == None:
			engagementStartleGame.__is_startled = False

		## taken from macroStartleRelax
		self.HT_STARTLE = 525	#530	#525
		self.HT_NEUTRAL = HT_MIDDLE
		self.HT_GS_DEFAULT = 15		## as set in Arbotix-M driver
		self.HT_GS_MAX = 75	#60	#50
		self.HT_GS_MIN = 10

		self.LL_STARTLE = LL_OPEN_MAX
		self.LL_NEUTRAL = LL_OPEN_DEFAULT
		self.LL_GS_DEFAULT = 100	## as set in Arbotix-M driver
		self.LL_GS_MIN = 10


		## Game variables
		if engagementStartleGame.__is_game_running == None:
			engagementStartleGame.__is_game_running = False
		if engagementStartleGame.__is_game_exit == None:
			engagementStartleGame.__is_game_exit = False
		self.ll_startle = LL_OPEN_MAX

		self.last_startle_time = None
		self.next_startle_time = None

		self.game_state = None

		self.repetitions = 6	## do 6 rounds of infant engagement behavior max

		self.duration_between_startle_min = 1.0		#2.0	## seconds
		self.duration_between_startle_max = 2.5		#5.0	## seconds

		## publisher for the experimenter 
		self.exp_pub = rospy.Publisher("experiment_info", String, queue_size = 10)

		return


	#################################
	##
	##	To run, publish to /maki_macro
	##		startleGame start
	##
	##	To stop, publish to /maki_macro
	##		startleGame stop
	##
	#################################
	## DO NOT USE -- UNDER DEVELOPMENT -- NOT FULLY TESTED	
	def runGame( self, repetitions=None, duration=None ):
		## duration in seconds
		rospy.logdebug("runGame: BEGIN")

		rospy.logwarn("runGame: BEGIN STATUS CHECKS...")
		## --- CHECK IF GAME IS ALREADY RUNNING ---
		if engagementStartleGame.__is_game_running:
			rospy.logerr("runGame: ERROR: GAME IS ALREADY RUNNING... Unable to begin a new game...")
			return False

		## --- CHECK INPUT ---
		if repetitions == None and duration == None:	
			repetitions = self.repetitions
			rospy.logwarn("runGame(): WARNING: NO INPUTS SPECIFIED... Defaulting to " + str(repetitions) + " repetitions MAXIMUM")

		elif (isinstance(repetitions, int)):
			if (repetitions > 0):
				pass
			else:
				rospy.logerr("runGame: INVALID INPUT: repetitions must be interger of minimum 1.... Unable to begin a new game...")
				return False

		elif (isinstance(duration, int) or isinstance(duration, float)):
			if (duration > 0):
				## estimate the maximum number of repetitions
				repetitions = float( duration / self.duration_between_startle_min )
				repetitions = int( repetitions + 0.5 )	## implicit rounding
			else:
				rospy.logerr("runGame: INVALID INPUT: duration must be a positive float (units in seconds)... Unable to begin a new game...")
				return False
		else:
			rospy.logerr("runGame: INVALID INPUT: repetitions is a non-integer value AND/OR duration is a non-integer/non-float value... Unable to begin a new game...")
			return False

		rospy.logwarn("runGame: SUCCESS: Initializing a new game... One moment please!...")
		engagementStartleGame.requestFeedback( self, SC_GET_PT )

		self.game_state = 0
		##	0: perform initial startle
		##	1: wait for infant to attend or not
		##	2: perform hideFromStartle
		##	3: choose a random period of time before trying again
		##	4: wait for the period of time before trying again
		##	5: perform unhideIntoStartle
		##	9: perform startle relax

		## TODO: May have to adjust _wait_attend value
		_wait_attend = 5	## wait 500 ms after arriving in startle position
		self.count_movements = 0
		_initial_startle = True
		#_duration_to_startle = float( self.startle_action_duration ) 
		_start_time = rospy.get_time()
		self.next_startle_time = _start_time
		engagementStartleGame.__is_game_running = True
		engagementStartleGame.__is_game_exit = False
		_break_flag = False

		rospy.logwarn("runGame: NEW GAME CREATED... Welcome!! Let's play a game...")
		## this is a nested while loop
		## A Python error was VERY PROBABLY being thrown here
		##while engagementStartleGame and self.ALIVE and (not rospy.is_shutdown()):
		while (engagementStartleGame.__is_game_running and (not engagementStartleGame.__is_game_exit) and 
			(not _break_flag) and self.ALIVE and (not rospy.is_shutdown())):
			_duration = abs(rospy.get_time() - _start_time)

			## NOTE: This outer while loop will cease IF:
			##	1) __is_game_running is toggled to False
			##	2) __is_game_exit is toggled to True -- Finish cleaning up from the game	
			##	3) self.mTT_INTERRUPT is toggled to True -- engagementStartleGame.stop() is called
			##	4) The duration of the game has been exceeded, if a duration was specified

			if self.mTT_INTERRUPT:	
				rospy.logdebug("mTT_INTERRUPT=" + str(self.mTT_INTERRUPT))
				_break_flag = True
				break	## exit the while loop
			elif (duration != None) and ((rospy.get_time() - _start_time) > duration):
				## TODO: How to clean up from this???
				rospy.logwarn(">>>>>>>>> runGame: The End... TIME's UP!!")
				_break_flag = True
				break	## exit the while loop
			else:
				## FPTZ request published takes 100ms to propogate
				engagementStartleGame.requestFeedback( self, SC_GET_PT )

			## STEP 0: begin the game with a startle
			if _initial_startle and (self.game_state == 0):
				rospy.logdebug("runGame(): STATE 0: BEGIN")
				rospy.logwarn("runGame(): STATE 0: Begin the game with a startle first -- ALWAYS...")
				engagementStartleGame.macroStartleRelax( self, startle=True, relax=False )
				self.last_startle_time = rospy.get_time()
				_initial_startle = False
				self.game_state = 1
				rospy.logdebug("runGame(): STATE 0: Initial startle complete, END... Changing to STATE 1...")
				continue	## start fresh at the top of the while loop
			#end	if _initial_startle and (self.game_state == 0):


			## STEP 1: wait for a moment to see if infant attends or not
			if (self.game_state == 1):
				rospy.logdebug("runGame(): wait after startle: BEGIN")
				rospy.logwarn("runGame(): STATE 1: Pausing... waiting to see if infant attends or not...")

				## Toggle _initial startle off; only happens once per game
				if _initial_startle:
					_initial_startle = False

				## did self.repetitions rounds of infant engagement behavior max?
				elif  (self.count_movements >= repetitions):
					rospy.logwarn(">>>>>>>>> runGame: The End... " + str(repetitions) + " IS THE MAXIMUM GAME ROUNDS PLAYED IN A SINGLE GAME!!... We could play again later...")
					self.exp_pub.publish('[Engagement game] End of game play')
					self.game_state = 9
					## this exit condition is self-terminating
					engagementStartleGame.__is_game_running = False
					_break_flag = True
					break	## jump out of the while loop

				else:
					rospy.logwarn("runGame(): STATE 1: Now playing ROUND #" + str(self.count_movements) + " of " + str(repetitions))
					self.exp_pub.publish('[Engagement game] Now playing ROUND #' + str(self.count_movements) + '' of '' + str(repetitions))
					_default_cmd_prop_duration = 100
					_c_duration = _wait_attend * _default_cmd_prop_duration
					for _c in range(_wait_attend):	## 0, 1, 2, 3, 4
						rospy.logdebug("runGame(): STATE 1: Duration remaining while waiting for infant to attend: " + str(_c_duration) + " milliseconds...")
						if self.mTT_INTERRUPT:	return
						#self.SWW_WI.sleepWhileWaitingMS( 100, end_early=False )
						## FPTZ request published takes 100ms to propogate
						engagementStartleGame.requestFeedback( self, SC_GET_PT )
						_c_duration = _c_duration - _default_cmd_prop_duration
					self.game_state = 2
					rospy.logwarn("runGame(): STATE 1: Infant did NOT attend while Maki-ro remained in startle expression...")
				rospy.logdebug("runGame(): STATE 1: wait after startle: END... Changing to STATE 2...")
				continue	## start fresh at the top of the while loop
			#end	if (self.game_state == 1):


			## STEP 2: if infant doesn't attend, hide before repeating
			if (self.game_state == 2):
				rospy.logdebug("runGame(): STATE 2: move into hide: BEGIN")
				rospy.logwarn("runGame(): STATE 2: Now Maki-ro will hide before repeating startle... If I can't see you, you can't see me!!")
				engagementStartleGame.hideFromStartle( self )
				self.game_state = 3
				rospy.logdebug("runGame(): STATE 2: Hide from startle completed, END... Changing to STATE 3...")
				continue	## start fresh at the top of the while loop
			#end	if (self.game_state == 2):


			## STEP 3: choose some random amout of time before trying again
			if (self.game_state == 3):
				rospy.logdebug("runGame(): STATE 3: choose next startle time: BEGIN")
				rospy.logwarn("runGame(): STATE 3: How long should Maki-ro stay hidden?...")
				## random.uniform yeilds a float
				_next_seconds = random.uniform( self.duration_between_startle_min, self.duration_between_startle_max )
				rospy.logwarn("runGame(): STATE 3: I'm thinking of a (floating point) number between " + str(self.duration_between_startle_min) + " and " + str(self.duration_between_startle_max) + "... Yup, you guessed it!! Maki-ro stay hidden for " + str(_next_seconds) + " seconds" )
				self.next_startle_time = rospy.get_time() + _next_seconds
				rospy.loginfo("runGame(): next startle in " + str(_next_seconds) + " seconds at time " + str(self.next_startle_time))
				self.game_state = 4
				_state4_first_pass = True
				rospy.logdebug("runGame(): STATE 3: choose next startle time: END... Changing to STATE 4")
				continue	## start fresh at the top of the while loop
			#end	if (self.game_state == 3):


			## STEP 4: wait until self.next_startle_time time before trying again
			if (self.game_state == 4):
				if _state4_first_pass:
					rospy.logdebug("runGame(): STATE 4: wait while hiding: BEGIN")
					rospy.logwarn("runGame(): STATE 4: Keeping hidden... No peaking!!")
					_state4_first_pass = False

				_remaining_hide_duration = self.next_startle_time - rospy.get_time()
				if (_remaining_hide_duration > 0.01):	## 100 ms
					rospy.loginfo("STATE 4: _remaining_hide_duration is " + str(_remaining_hide_duration) + " seconds")

					### FPTZ request published takes 100ms to propogate
					engagementStartleGame.requestFeedback( self, SC_GET_PT )
					self.SWW_WI.sleepWhileWaiting( 0.25, increment=0.05 )

					## TODO: SHOULD DO SOMETHING TO MAKE SURE HT IS NOT OVERHEATING

					continue	## start fresh at the top of the while loop
				else:
					### FPPZ request published takes 100ms to propogate
					engagementStartleGame.requestFeedback( self, SC_GET_PP )
					self.game_state = 5
					rospy.logwarn("runGame(): STATE 4: Hiding time's up... Let's see if Maki-ro can surprise the infant next!!")
				rospy.logdebug("runGame(): STATE 4: wait while hiding: END... Changing to STATE 5...")
				continue	## start fresh at the top of the while loop
			#end	if (self.game_state == 4):


			## STEP 5: try again! pop up from hiding
			if (self.game_state == 5):
				rospy.logdebug("runGame(): STATE 5: move out of hiding into startle: BEGIN")
				rospy.logwarn("runGame(): STATE 5: Ready or not, here goes... Destination: Bugged Out Face!!")
				self.count_movements = self.count_movements +1
				## FIXED: Only do full unhideIntoStartle while less than the number of repetitions
				if (self.count_movements < repetitions):
					engagementStartleGame.unhideIntoStartle( self )
				else:
					## Hit MAX reptitions... only unhide. DO NOT startle again...
					engagementStartleGame.unhideIntoStartle( self, unhide=True, startle=False )
				self.game_state = 1
				rospy.logwarn("runGame(): STATE 5: Maki-ro popped up so FAST... hopefully without whiplash!!!")
				rospy.logdebug("runGame(): STATE 5: move out of hiding into startle: END... Changing back to STATE 1")
				rospy.logerr("<<<<<<<<<<<<<<<<<<<<<<< END OF ROUND #" + str(self.count_movements) + " >>>>>>>>>>>>>>>>>>>>")
				continue	## start fresh at the top of the while loop
			#end	if (self.game_state == 5):


		#end	while self.ALIVE and not rospy.is_shutdown():

		_duration = rospy.get_time() - _start_time
		rospy.loginfo( "NUMBER OF STARTLE/HIDE ROUNDS: " + str(self.count_movements) )
		rospy.loginfo( "Duration: " + str(_duration) + " seconds" )

		rospy.logwarn("runGame(): Main game complete after playing " + str(self.count_movements) + " rounds... but wait!! There's more... Cleanup from STATE " + str(self.game_state) + "...")
		engagementStartleGame.__is_game_exit = True
		engagementStartleGame.__is_game_running = False		## for good measure
		rospy.logdebug("runGame: END")
		return

	def cleanupGame( self ):
		rospy.logdebug("cleanupGame(): BEGIN")
		## KATE -- TO TEST
		## break the while loop in runGame()
		rospy.loginfo("cleanupGame(): BEFORE: __is_game_running=" + str(engagementStartleGame.__is_game_running))
		engagementStartleGame.__is_game_running = False
		rospy.loginfo("cleanupGame(): BEFORE: __is_game_running=" + str(engagementStartleGame.__is_game_running))
		rospy.logwarn("cleanupGame(): Attempting to break runGame while loop... toggle __is_game_running to " + str(engagementStartleGame.__is_game_running) + "...")

		rospy.logwarn("cleanupGame(): Now waiting for paint to dry... Kidding... maybe...")
		_start_wait_time = rospy.get_time()
		## the following while loop will terminate when runGame() returns
		while (not engagementStartleGame.__is_game_exit) and (not rospy.is_shutdown()):
			#self.SWW_WI.sleepWhileWaitingMS( 100, end_early=False )
			rospy.loginfo("cleanupGame(): Are we there yet? Been waiting " + str( rospy.get_time() - _start_wait_time ) + " seconds... __is_game_running=" + str(engagementStartleGame.__is_game_running) + " and __is_game_exit=" + str(engagementStartleGame.__is_game_exit))
		rospy.logwarn("cleanupGame(): FINALLY!! It took " + str( rospy.get_time() - _start_wait_time ) + " seconds before runGame() returned... and in a fine STATE " + str(self.game_state))

		rospy.logwarn("cleanupGame(): Alrighty, let's get to work putting Maki-ro's head back on straight... I hear there's a good movie playing soon...")
		## CLEAN UP and move Maki-ro into neutral eyelid (LL) and head tilt (HT) positions
		if (self.game_state == 9):
			## the game ended after max repetitions
			rospy.logwarn("cleanupGame(): runGame was in STATE 9: repetitions exceeded... Awwwwwww, guess Maki-ro needs to relax from startle")
			engagementStartleGame.macroStartleRelax( self, startle=False, relax=True )
			rospy.logwarn("cleanupGame(): Relaxed Maki-ro is going to see the movie, even if no one else is interested...")

		elif (self.game_state == 1):
			## Maki-ro is in startle position
			rospy.logwarn("cleanupGame(): runGame was in STATE 1: wait while loop interrupted with Maki-ro still in startle position, so relax... INFANT ENGAGED WITH EYE CONTACT!!!!!!!!!!!")
			engagementStartleGame.macroStartleRelax( self, startle=False, relax=True )
			rospy.logwarn("cleanupGame(): Relaxed Maki-ro and new pal are going together to see movie...") 

		else:
			## Maki-ro is in hiding position
			rospy.logwarn("cleanupGame(): runGame was in STATE " + str(self.game_state) + ": while loop interrupted with Maki-ro in sleepy-head hide position...")
			try:
				## THIS IS CUSTOM RESET
				##	reset goal speeds and goal positions
				##	and monitor moving into goal positions
				engagementStartleGame.monitorMoveToGP( self, "reset", ht_gp=self.HT_NEUTRAL, ll_gp=self.LL_NEUTRAL )
				rospy.logwarn("cleanupGame(): POKE!! Wake up sleepy-head Maki-ro... Infant either likes your hair, or wants to see a movie...")
			except rospy.exceptions.ROSException as _e:
				rospy.logerr("cleanupGame(): ERROR: UNABLE TO RESET MAKI-RO TO NEUTRAL POSITIONS: " + str(_e))
				### Uh-oh... this is a last ditch effort
				#engagementStartleGame.pubTo_maki_command( self, "reset" )
				#return False

				### Workaround is to use only the first half of unhideIntoStartle
				engagementStartleGame.unhideIntoStartle( self, unhide=True, startle=False )

		rospy.logdebug("cleanupGame(): END")
		return True

	############################
	##
	##	To run, publish to /maki_macro:
	##		hideFromStartle
	##
	############################
	def hideFromStartle( self ):
		if (engagementStartleGame.__is_startled == False):	
			rospy.logerr("hideFromStartle: INVALID STATE: engagementStartleGame.__is_startled=" + str(engagementStartleGame.__is_startled))
			return

		## (_gs_ll, _gs_ht)
		## distance covered in 200 ms timestepd
		## ((50%, 20%), (50%, 40%), (0%, 25%), (0%, 10%), (0%, 5%))
		_gs_sequence = ((192,29), (192,57), (192,36), (192,14), (192,7))
		_duration_into_hide = 1000	## milliseconds
		_step_duration = float( _duration_into_hide / len(_gs_sequence) )

		_pub_cmd = ""

		_start_time = rospy.get_time()
		if engagementStartleGame.__is_startled and (self.ALIVE) and (not self.mTT_INTERRUPT) and (not rospy.is_shutdown()):

			_ll_gp = LL_CLOSE_MAX
			_ht_gp = HT_DOWN

			engagementStartleGame.requestFeedback( self, SC_GET_PP )
			_ll_start_pp = self.makiPP["LL"]
			_ht_start_pp = self.makiPP["HT"] 
			
			_loop_count = 0
			_first_pass = True
			for _gs_ll, _gs_ht in _gs_sequence:
				_start_time_step = rospy.get_time()

				_pub_cmd = ""
				_pub_cmd += "LLGS" + str(_gs_ll)
				_pub_cmd += "HTGS" + str(_gs_ht)
				_pub_cmd += TERM_CHAR_SEND
				rospy.loginfo( _pub_cmd )
				engagementStartleGame.pubTo_maki_command( self, _pub_cmd, cmd_prop=True )
				## has 100 ms delay for propogation to motors

				if _first_pass:
					_pub_cmd = ""
					_pub_cmd += "LLGP" + str(_ll_gp)
					_pub_cmd += "HTGP" + str(_ht_gp)
					_pub_cmd += TERM_CHAR_SEND
					rospy.logwarn( _pub_cmd )
					engagementStartleGame.pubTo_maki_command( self, _pub_cmd, cmd_prop=True )

					## KATE -- TO TEST
					## confirm that the goal positions have been set
					engagementStartleGame.requestFeedback( self, SC_GET_GP )
					if ( str(SC_GET_GP) in self.maki_feedback_values and
						_ll_gp == self.maki_feedback_values[ str(SC_GET_GP) ]["LL"] and
						_ht_gp == self.maki_feedback_values[ str(SC_GET_GP) ]["HT"]):
						_first_pass = False
			
				if (abs(rospy.get_time() - _start_time) < _duration_into_hide):
					## has 100 ms delay for propogation to motors
					engagementStartleGame.requestFeedback( self, SC_GET_PP )

					## compensate to maintain pacing of 200 ms apart
					_adjusted_sleep = _step_duration - abs(rospy.get_time() - _start_time_step)
					if (_adjusted_sleep <= 0):
						rospy.logdebug("... no sleep _step_duration adjustment")
					else:	
						rospy.logdebug( str(_adjusted_sleep) + " milliseconds more are needed to fulfill _step_duration pacing")
						self.SWW_WI.sleepWhileWaitingMS( _adjusted_sleep, end_early=False )

					## KATE -- TO TEST
					if ((abs(_ll_gp - self.makiPP["LL"]) < DELTA_PP) and
						((abs(_ht_gp - self.makiPP["HT"]) < DELTA_PP))):
						rospy.logdebug("Arrived at hide position")
						break

					_loop_count = _loop_count +1
				else:
					rospy.logdebug("hideFromStartle(): TIME IS UP")
					break	

			#end	for _gs_ll, _gs_ht in _gs_sequence:

			## KATE -- TO TEST
			#engagementStartleGame.__is_startled = False
		else:
			return False
		#end	if engagementStartle.__is_startled and Game(self.ALIVE) and (not self.mTT_INTERRUPT) and (not rospy.is_shutdown()):

		_duration = abs(rospy.get_time() - _start_time)
		rospy.loginfo( "NUMBER OF TIMESTEPS: " + str(_loop_count) )
		rospy.loginfo( "Duration: " + str(_duration) + " seconds" )

		## KATE -- TO TEST
		if ((abs(_ll_gp - self.makiPP["LL"]) < DELTA_PP) and
			((abs(_ht_gp - self.makiPP["HT"]) < DELTA_PP))):
			engagementStartleGame.__is_startled = False
		else:
			return False

		rospy.logdebug("hideFromStartle: END")
		return True

	############################
	##
	##	To run, publish to /maki_macro:
	##		unhideIntoStartle
	##
	############################
	def unhideIntoStartle( self, unhide=True, startle=True ):
		rospy.logdebug("unhideIntoStartle: BEGIN")

		## Check to make sure that both inputs are boolean, 
		##	and at least one has the value True
		if ((isinstance(unhide, bool)) and (isinstance(startle, bool)) and
			(unhide or startle)):
			pass
		else:
			rospy.logerror("unhideIntoStartle(): INVALID INPUTS")
			return False

		if unhide:
			### resets all servo motors to neutral position
			### resets goal speeds too
			#engagementStartleGame.pubTo_maki_command( self, "reset" )	

			## reset to neutral position
			_pub_cmd = ""
			_pub_cmd += "HT" + SC_SET_GS + str(self.HT_GS_DEFAULT)
			_pub_cmd += "HT" + SC_SET_GP + str(self.HT_NEUTRAL)
			_pub_cmd += "LL" + SC_SET_GS + str(self.LL_GS_DEFAULT)
			_pub_cmd += "LL" + SC_SET_GP + str(self.LL_NEUTRAL)
			_pub_cmd += TERM_CHAR_SEND
			engagementStartleGame.pubTo_maki_command( self, _pub_cmd )
			
			## NOTE: The following was emperically determined
			## wait for reset motion to complete
			## meanwhile, print out the present speeds while moving
			#for _i in range(10):
			for _i in range(4):
				engagementStartleGame.requestFeedback( self, SC_GET_PS )
				#self.SWW_WI.sleepWhileWaitingMS( 100, end_early=False )		
				self.SWW_WI.sleepWhileWaitingMS( 250, end_early=False )		
			rospy.logdebug("unhideIntoStartle(): unhide behavior executed")

		if startle:
			## move into startle
			engagementStartleGame.macroStartleRelax( self, relax=False )
			rospy.logdebug("unhideIntoStartle(): startle behavior executed")

		rospy.logdebug("unhideIntoStartle: END")
		return

	############################
	##	To run, publish to /maki_macro:
	##		startle start
	##
	##	To stop, publish to /maki_macro:
	##		startle stop
	##
	## By default, Maki-ro will perform one startle action followed by
	## one relax action and stop
	############################
	def macroStartleRelax( self, startle=True, relax=True, repetitions=1 ):
		rospy.logdebug("macroStartleRelax(): BEGIN")

		_start_time = rospy.get_time()
		## check the inputs
		if isinstance(startle, bool) and (not startle) and isinstance(relax, bool) and (not relax):	return
		if isinstance(repetitions, int) and (repetitions > 0):
			pass
		else:
			rospy.logwarn("macroStartleRelax(): INVALID VALUE: repetitions=" + str(repetitions) + "; updated to 1")
			repetitions = 1

		## generate servo control command to set goal positions
		## NOTE: on the Arbotix-M side, a sync_write function is used
		## to simultaneously broadcast the updated goal positions
		_startle_gp_cmd = ""
		_startle_gp_cmd += "LL" + SC_SET_GP + str(self.LL_STARTLE)
		_startle_gp_cmd += "HT" + SC_SET_GP + str(self.HT_STARTLE)
		_startle_gp_cmd += TERM_CHAR_SEND
		_relax_gp_cmd  = ""
		_relax_gp_cmd += "LL" + SC_SET_GP + str(self.LL_NEUTRAL)
		_relax_gp_cmd += "HT" + SC_SET_GP + str(self.HT_NEUTRAL)
		_relax_gp_cmd += TERM_CHAR_SEND
		_pub_cmd = ""

		## Store initial pose
		engagementStartleGame.requestFeedback( self, SC_GET_PP )
		_previous_ll = self.makiPP["LL"]
		_previous_ht = self.makiPP["HT"]

		if relax and (not startle):
			rospy.loginfo("relax ONLY... skip alignment")
			pass
		else:
			## Move to neutral eyelid and head tilt pose
			rospy.loginfo("BEFORE startle, adjust LL and HT to NeutralPose")
			_pub_cmd = ""
			if (abs(self.makiPP["LL"] - self.LL_NEUTRAL) > DELTA_PP):
				_pub_cmd += "LLGP" + str(self.LL_NEUTRAL)
			if (abs(self.makiPP["HT"] - self.HT_NEUTRAL) > DELTA_PP):
				_pub_cmd += "HTGP" + str(self.HT_NEUTRAL) 
			if ( len(_pub_cmd) > 0 ):
				_pub_cmd += TERM_CHAR_SEND
				try:
					engagementStartleGame.monitorMoveToGP( self, _pub_cmd, ll_gp=self.LL_NEUTRAL, ht_gp=self.HT_NEUTRAL )
				except rospy.exceptions.ROSException as _e:
					rospy.logerr( str(_e) )
				#self.SWW_WI.sleepWhileWaiting(1)	## 1 second	## debugging

		_duration = abs(rospy.get_time() -_start_time)
		rospy.loginfo("OVERHEAD SETUP TIME: " + str(_duration) + " seconds")

		## TODO: unify duration_startle
		#_duration_startle = 100		## millisecond
		_duration_relax = 1000		## milliseconds
		_duration_relax_wait = 250
		_loop_count = 0
		_start_time = rospy.get_time()
		while (_loop_count < repetitions) and (self.ALIVE) and (not self.mTT_INTERRUPT) and (not rospy.is_shutdown()):
			rospy.logdebug("-------------------")

			if startle:
				rospy.loginfo("====> STARTLE")
				engagementStartleGame.requestFeedback( self, SC_GET_PP )
				rospy.logdebug( str(self.makiPP) )

				## Calculate goal speed base on distance and duration (in milliseconds)
				_duration_startle = 100		## millisecond
				_distance_to_startle_ll = abs( self.makiPP["LL"] - self.LL_STARTLE )
				rospy.logdebug("_distance_startle_ll=" + str(_distance_to_startle_ll))
				_gs_ll = abs( self.DC_helper.getGoalSpeed_ticks_durationMS( _distance_to_startle_ll, _duration_startle) )
				rospy.loginfo("_gs_ll=" + str(_gs_ll))

				_duration_startle = 150	#200	#250		## millisecond
				_distance_to_startle_ht = abs( self.makiPP["HT"] - self.HT_STARTLE )
				rospy.logdebug("_distance_startle_ht=" + str(_distance_to_startle_ht))
				_gs_ht = abs( self.DC_helper.getGoalSpeed_ticks_durationMS( _distance_to_startle_ht, _duration_startle) )
				rospy.loginfo("_gs_ht=" + str(_gs_ht))
				_gs_ht = min(_gs_ht, self.HT_GS_MAX)
				rospy.loginfo("adjusted _gs_ht=" + str(_gs_ht))

				## preset the desired goal speeds BEFORE sending the goal positions
				_pub_cmd = ""
				_pub_cmd += "LL" + SC_SET_GS + str(_gs_ll)
				_pub_cmd += "HT" + SC_SET_GS + str(_gs_ht)
				## NOTE: pubTo_maki_command will automatically add TERM_CHAR_SEND postfix

				## publish and give time for the command to propogate to the servo motors
				engagementStartleGame.pubTo_maki_command( self, str(_pub_cmd), cmd_prop=True )

				## set servo control command to set goal positions
				_pub_cmd = _startle_gp_cmd

				_start_time_startle = rospy.get_time()
				try:
					## Maki-ro open eyes wide
					## and "jerks" head back
					engagementStartleGame.pubTo_maki_command( self, _pub_cmd )
					## NOTE: publish and give time for the command to propogate to the servo motors,
					## but DO NOT MONITOR (excess overhead of minimum 200ms, which is greater
					## than _duration_startle and will cause delay)
					#engagementStartleGame.monitorMoveToGP( self, _pub_cmd, ll_gp=self.LL_STARTLE, ht_gp=self.HT_STARTLE)
				except rospy.exceptions.ROSException as e1:
					rospy.logerr( str(e1) )
				_duration = abs(_start_time_startle - rospy.get_time())
				rospy.logwarn( "Startle duration: " + str(_duration) + " seconds" )

				engagementStartleGame.__is_startled = True
				rospy.loginfo("Done: STARTLE ====")
			#end	if startle:

			if relax:
				rospy.loginfo("====> RELAX")
				rospy.loginfo( str(self.makiPP) )
				_first_pass = True
				_start_time_relax = rospy.get_time()

				## own version of monitorMoveToGP
				## adjusts speed based on difference
				## between current position and goal
				## position to stay within _duration_relax
				while relax and (not rospy.is_shutdown()):
					engagementStartleGame.requestFeedback( self, SC_GET_PP )
					rospy.loginfo( str(self.makiPP) )

					## computer difference between current and goal positions
					## TODO: do this calculation using map
					_distance_to_relax_ll = abs( self.makiPP["LL"] - self.LL_NEUTRAL )
					rospy.loginfo("_distance_to_relax_ll=" + str(_distance_to_relax_ll))
					_distance_to_relax_ht = abs( self.makiPP["HT"] - self.HT_NEUTRAL )
					rospy.loginfo("_distance_to_relax_ht=" + str(_distance_to_relax_ht))

					## adjust duration to stay within _duration_relax
					if _first_pass:
						rospy.logdebug("duration_relax = " + str(_duration_relax))
						_first_pass=False
						pass
					elif (_distance_to_relax_ll > DELTA_PP) or (_distance_to_relax_ht > DELTA_PP):
						_duration_relax = _duration_relax - _duration_relax_wait
						rospy.logdebug("duration_relax = " + str(_duration_relax))
					else:
						rospy.logdebug("close enough...done relax while loop")
						break
					if (_duration_relax <= 0):
						rospy.logdebug("negative time...done relax while loop")
						break

					## calculate new goal speeds
					_gs_ll = self.DC_helper.getGoalSpeed_ticks_durationMS( _distance_to_relax_ll, _duration_relax)
					rospy.loginfo("_gs_ll=" + str(_gs_ll))
					_gs_ll = max(_gs_ll, self.LL_GS_MIN)
					rospy.loginfo("adjusted _gs_ll=" + str(_gs_ll))
					_gs_ht = self.DC_helper.getGoalSpeed_ticks_durationMS( _distance_to_relax_ht, _duration_relax)
					rospy.loginfo("_gs_ht=" + str(_gs_ht))
					_gs_ht = max(_gs_ht, self.HT_GS_MIN)
					rospy.loginfo("adjusted _gs_ht=" + str(_gs_ht))
					#_duration_relax_wait = self.DC_helper.getTurnDurationMS_ticks_goalSpeed( _distance_to_relax, _gs_ll )
					#rospy.loginfo("waitMS = " + str(_duration_relax_wait))
			
					## generate servo control command to set new goal speeds
					_pub_cmd = ""
					_pub_cmd += "LL" + SC_SET_GS + str(_gs_ll)
					_pub_cmd += "HT" + SC_SET_GS + str(_gs_ht)
					engagementStartleGame.pubTo_maki_command( self, str(_pub_cmd) )

					## servo control command to set goal positions
					_pub_cmd = _relax_gp_cmd
		
					#_start_time_relax = rospy.get_time()
					try:
						## Maki-ro relaxes wide open eyes
						## and head comes back forward to neutral
						engagementStartleGame.pubTo_maki_command( self, _pub_cmd )
						self.SWW_WI.sleepWhileWaitingMS( _duration_relax_wait, end_early=False)
					except rospy.exceptions.ROSException as e2:
						rospy.logerr( str(e2) )
				#end	while relax and (not rospy.is_shutdown()):

				_duration = abs(_start_time_relax - rospy.get_time())
				rospy.logwarn( "Relax duration: " + str(_duration) + " seconds" )
				rospy.loginfo( str(self.makiPP) )

				engagementStartleGame.__is_startled = False
				rospy.loginfo("Done: RELAX ====")
			#end	if relax:

			_loop_count = _loop_count +1

			## debugging
			#rospy.loginfo(".............P A U S E ...")
			#self.SWW_WI.sleepWhileWaiting( 1 )	## 1 second
		# end	while not rospy.is_shutdown():

		_duration = abs(rospy.get_time() - _start_time)
		rospy.logdebug( "NUMBER OF STARTLE/RELAX MOVMENTS: " + str(_loop_count) )
		rospy.logdebug( "Duration: " + str(_duration) + " seconds" )
		return


	def startStartle( self, relax=False ):
		rospy.logdebug("startStartle(): BEGIN")
		## call base class' start function
		eyelidHeadTiltBaseBehavior.start(self)
		rospy.logdebug("startStartle(): After eyelidHeadTiltBaseBehavior.start()")
		engagementStartleGame.macroStartleRelax( self, startle=True, relax=relax )
		rospy.logdebug("startStartle(): END")
		return

	def stopStartle( self ):
		## shift into eyelid and headtilt neutral
		engagementStartleGame.macroStartleRelax( self, startle=False, relax=True )

		## call base class' stop function
		eyelidHeadTiltBaseBehavior.stop(self)
		return

	## DO NOT USE -- UNDER DEVELOPMENT -- NOT FULLY TESTED	
	def startStartleGame( self ):
		## call base class' start function
		eyelidHeadTiltBaseBehavior.start(self)

		engagementStartleGame.setEyelidNeutralPose( self, LL_OPEN_DEFAULT, monitor=True )

		engagementStartleGame.requestFeedback( self, SC_GET_PP )
		## set to startle game values for neutral eyelid
		engagementStartleGame.setEyelidRange( self, self.makiPP["LL"], ll_startle=LL_OPEN_MAX, ll_close=LL_CLOSE_MAX )

		### should immediately begin with startle
		#self.next_startle_time = rospy.get_time()
		#rospy.logdebug("startStartle(): next_startle_time=" + str(self.next_startle_time))
		### NOTE: initial startle is taken care of in runGame()

		engagementStartleGame.runGame( self )
		return

	## DO NOT USE -- UNDER DEVELOPMENT -- NOT FULLY TESTED	
	def stopStartleGame( self, disable_ht=True ):
		rospy.logdebug("stopStartleGame(): BEGIN")

		## NOTE: cleanupGame() is blocking -- CAREFUL
		if engagementStartleGame.cleanupGame( self ):
			rospy.logdebug("stopStartleGame(): cleanupGame was SUCCESSFUL")
		else:
			## trying to signal the MAKI PILOT for HELP
			rospy.logerr("stopStartleGame():\t!!!!!!!!!!!!!!  HELP   HELP   HELP   HELP   HELP   !!!!!!!!!!!")
			for _c in range(10):
				rospy.logerr("stopStartleGame(): cleanupGame either FAILED or is INCOMPLETE... !!!!!!!!!!!!! SHOULD THE MAKI PILOT INTERVENE ?")
			rospy.logerr("stopStartleGame():\t!!!!!!!!!!!!!!  HELP   HELP   HELP   HELP   HELP   !!!!!!!!!!!")

		## call base class' stop function
		eyelidHeadTiltBaseBehavior.stop(self, disable_ht=disable_ht)

		## reset to single startle values from neutral eyelid
		engagementStartleGame.setEyelidRange( self, LL_OPEN_DEFAULT, ll_close=LL_CLOSE_MAX )
		self.next_startle_time = None

		rospy.logdebug("stopStartleGame(): END")
		return

	## override
	def setEyelidRange( self, ll, ll_delta=None, ll_close=None, ll_startle=None ):
		## call to base class' function; eyelidBaseBehavior in this case
		eyelidBaseBehavior.setEyelidRange( self, ll, ll_delta, ll_close )

		if ll_startle == None:	return

		## override base class's function
		self.ll_startle = ll_startle	## passed position

		## check range values
		if self.ll_startle > LL_OPEN_MAX:	self.ll_startle = LL_OPEN_MAX
		rospy.logdebug("Startle -- Eyelid range: (" + str(self.ll_close) + ", " + str(self.ll_open) + ", " + str(self.ll_startle) + ")")
		return

	def parse_maki_macro( self, msg ):
		rospy.loginfo( msg.data )

		if msg.data == "startle":
			## one startle and one relax
			engagementStartleGame.startStartle( self, relax=True )

		elif msg.data == "startle start":
			## one startle and do not relax
			engagementStartleGame.startStartle( self, relax=False )

		elif (msg.data == "startle stop") or (msg.data == "startle relax"):
			## one relax without startle
			## NOTE: disables HT
			engagementStartleGame.stopStartle( self )

		elif (msg.data == "hideFromStartle"):
			## from startle position, move to hide
			engagementStartleGame.hideFromStartle( self )

		elif (msg.data == "unhideIntoStartle"):
			## from hide position, move to startle
			engagementStartleGame.unhideIntoStartle( self )

		elif (msg.data == "startleGame start"):
			## NOTE: This call is blocking
			try:
				## start the infant engagement game
				thread.start_new_thread( engagementStartleGame.startStartleGame, (self, ))
			except:
				rospy.logerr("Unable to start new thread for engagementStartleGame.startStartleGame()")

		elif (msg.data.startswith( "startleGame stop") ):
			## stop the infant engagement game
			## NOTE: Also disables HT unless otherwise specified
			if msg.data.endswith( "disable_ht=False" ):
				engagementStartleGame.stopStartleGame( self, disable_ht=False )
			else:
				engagementStartleGame.stopStartleGame( self )

		else:
			pass

		return

if __name__ == '__main__':
        print "__main__: BEGIN"
	E = engagementStartleGame( True, None )

	rospy.Subscriber( "/maki_macro", String, E.parse_maki_macro )
        rospy.logdebug( "now subscribed to /maki_macro" )

	rospy.spin()   ## keeps python from exiting until this node is stopped

        print "__main__: END"


