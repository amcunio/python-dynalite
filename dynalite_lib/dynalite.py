"""
@ Author      : Troy Kelly
@ Date        : 3 Dec 2018
@ Description : Philips Dynalite Library - Unofficial interface for Philips Dynalite over RS485

@ Notes:        Requires a RS485 to IP gateway (Do not use the Dynalite one - use something cheaper)
"""

import asyncio
import logging
import json
from .dynet import Dynet, DynetControl

CONF_HOST = 'host'
CONF_LOGLEVEL = 'log_level'
CONF_LOGFORMATTER = 'log_formatter'
CONF_PORT = 'port'
CONF_DEFAULT = 'default'
CONF_AREA = 'area'
CONF_NAME = 'name'
CONF_FADE = 'fade'
CONF_PRESET = 'preset'
CONF_AUTODISCOVER = 'autodiscover'
CONF_POLLTIMER = 'polltimer'
CONF_CHANNEL = 'channel'
CONF_NODEFAULT = 'nodefault'

class BroadcasterError(Exception):
    def __init__(self, message):
        self.message = message


class PresetError(Exception):
    def __init__(self, message):
        self.message = message


class ChannelError(Exception):
    def __init__(self, message):
        self.message = message


class AreaError(Exception):
    def __init__(self, message):
        self.message = message


class Event(object):

    def __init__(self, eventType=None, message=None, data={}):
        self.eventType = eventType.upper() if eventType else None
        self.msg = message
        self.data = data

    def toJson(self):
        return json.dumps(self.__dict__)


class DynaliteConfig(object):

    def __init__(self, config=None):
        self.log_level = config[CONF_LOGLEVEL].upper(
        ) if CONF_LOGLEVEL in config else logging.INFO
        self.log_formatter = config[
            CONF_LOGFORMATTER] if CONF_LOGFORMATTER in config else "[%(asctime)s] %(name)s {%(filename)s:%(lineno)d} %(levelname)s - %(message)s"
        self.host = config[CONF_HOST] if CONF_HOST in config else 'localhost'
        self.port = config[CONF_PORT] if CONF_PORT in config else 12345
        self.default = config[CONF_DEFAULT] if CONF_DEFAULT in config else {}
        self.area = config[CONF_AREA] if CONF_AREA in config else {}
        self.preset = config[CONF_PRESET] if CONF_PRESET in config else {}
        self.autodiscover = config[CONF_AUTODISCOVER] if CONF_AUTODISCOVER in config else True # autodiscover by default
        self.polltimer = config[CONF_POLLTIMER] if CONF_POLLTIMER in config else 1 # default poll 1 sec


class Broadcaster(object):

    def __init__(self, listenerFunction=None, loop=None, logger=None):
        if listenerFunction is None:
            raise BroadcasterError(
                "A broadcaster bust have a listener Function")
        self._listenerFunction = listenerFunction
        self._monitoredEvents = []
        self._loop = loop
        self._logger = logger

    def monitorEvent(self, eventType=None):
        if eventType is None:
            raise BroadcasterError("Must supply an event type to monitor")
        eventType = eventType.upper()
        if eventType not in self._monitoredEvents:
            self._monitoredEvents.append(eventType.upper())

    def unmonitorEvent(self, eventType=None):
        if eventType is None:
            raise BroadcasterError("Must supply an event type to un-monitor")
        eventType = eventType.upper()
        if eventType in self._monitoredEvents:
            self._monitoredEvents.remove(eventType.upper())

    def update(self, event=None, dynalite=None):
        if event is None:
            return
        if event.eventType not in self._monitoredEvents and '*' not in self._monitoredEvents:
            return
        if self._loop:
            self._loop.create_task(self._callUpdater(
                event=event, dynalite=dynalite))
        else:
            self._listenerFunction(event=event, dynalite=dynalite)

    @asyncio.coroutine
    def _callUpdater(self, event=None, dynalite=None):
        self._listenerFunction(event=event, dynalite=dynalite)


class DynalitePreset(object):

    def __init__(self, name=None, value=None, fade=2, logger=None, broadcastFunction=None, area=None, dynetControl=None):
        if not value:
            raise PresetError("A preset must have a value")
        self._logger = logger
        self.active = False
        self.name = name if name else "Preset " + str(value)
        self.value = int(value)
        self.fade = float(fade)
        self.area = area
        self.broadcastFunction = broadcastFunction
        self._control = dynetControl
        if self.broadcastFunction:
            broadcastData = {
                'area': self.area.value,
                'preset': self.value,
                'name': self.area.name + ' ' + self.name,
                'state': 'OFF'
            }
            self.broadcastFunction(
                Event(eventType='NEWPRESET', data=broadcastData)
            )

    def turnOn(self, sendDynet=True, sendMQTT=True):
        self.active = True
        if self.area:
            self.area.activePreset = self.value
        if sendMQTT and self.broadcastFunction:
            broadcastData = {
                'area': self.area.value,
                'preset': self.value,
                'name': self.area.name + ' ' + self.name,
                'state': 'ON'
            }
            self.broadcastFunction(
                Event(eventType='PRESET', data=broadcastData))
        if sendDynet and self._control:
            self._control.areaPreset(
                area=self.area.value, preset=self.value, fade=self.fade)
        for preset in self.area.preset:
            if self.value != preset:
                if self.area.preset[preset].active:
                    self.area.preset[preset].turnOff(
                        sendDynet=False, sendMQTT=True)

    def turnOff(self, sendDynet=True, sendMQTT=True):
        self.active = False
        if sendMQTT and self.broadcastFunction:
            broadcastData = {
                'area': self.area.value,
                'preset': self.value,
                'name': self.area.name + ' ' + self.name,
                'state': 'OFF'
            }
            self.broadcastFunction(
                Event(eventType='PRESET', data=broadcastData))
        if sendDynet and self._control:
            self._control.areaOff(area=self.area.value, fade=self.fade) # XXX TODO check if this behavior is correct. In general, you select a preset, so there is no real "turn-off"

class DynaliteChannel(object):

    def __init__(self, name=None, value=None, fade=2, presets=None, logger=None, broadcastFunction=None, area=None, dynetControl=None):
        logger.debug("DynaliteChannel init called area=%s channel=%s fade=%s" % (area.value, value, fade))
        if not value:
            raise ChannelError("A channel must have a value")
        self._logger = logger
        self.level = 0
        self.name = name if name else "Channel " + str(value)
        self.value = int(value)
        self.fade = float(fade)
        self.presets = presets
        self.area = area
        self.broadcastFunction = broadcastFunction
        self._control = dynetControl
        if self.broadcastFunction:
            broadcastData = {
                'area': self.area.value,
                'channel': self.value,
                'name': self.area.name + ' ' + self.name,
                'level': self.level
            }
            self.broadcastFunction(
                Event(eventType='NEWCHANNEL', data=broadcastData))
        self.requestChannelLevel() # ask for the initial level

    def turnOn(self, brightness=1.0, sendDynet=True, sendMQTT=True):
        if sendDynet and self._control:
            self._control.setChannel(
                area=self.area.value, channel=self.value, level=brightness, fade=self.fade)

    def turnOff(self, sendDynet=True, sendMQTT=True): 
        if sendDynet and self._control:
             self._control.setChannel(
                area=self.area.value, channel=self.value, level=0, fade=self.fade)
                
    def requestChannelLevel(self):
        self.area.requestChannelLevel(self.value)
        
    def stopFade(self):
        self._control.stop_channel_fade(area=self.area.value, channel=self.value) 
        
    def getLevel(self):
        return self.level

    def setLevel(self, level):
        self.level = level


class DynaliteArea(object):

    def __init__(self, name=None, value=None, fade=2, areaPresets=None, defaultPresets=None, areaChannels=None, areaType=None, onPreset=None, offPreset=None, logger=None, broadcastFunction=None, dynetControl=None):
        if not value:
            raise PresetError("An area must have a value")
        self._logger = logger
        self.name = name if name else "Area " + str(value)
        self.type = areaType.lower() if areaType else 'light'
        self.value = int(value)
        self.fade = fade
        self.preset = {}
        self.channel = {}
        self.activePreset = None
        self.state = None

        if self.type == 'cover':
            self._onName = 'OPEN'
            self._offName = 'CLOSED'
            if onPreset is not None:
                self.openPreset = onPreset
            if offPreset is not None:
                self.closePreset = offPreset
        else:
            self._onName = 'ON'
            self._offName = 'OFF'
            if onPreset is not None:
                self.onPreset = onPreset
            if offPreset is not None:
                self.offPreset = offPreset

        self.broadcastFunction = broadcastFunction
        self._dynetControl = dynetControl
        if areaPresets:
            for presetValue in areaPresets:
                preset = areaPresets[presetValue]
                presetName = preset[CONF_NAME] if CONF_NAME in preset else None
                presetFade = preset[CONF_FADE] if CONF_FADE in preset else fade
                self.preset[int(presetValue)] = DynalitePreset(
                    name=presetName, 
                    value=presetValue, 
                    fade=presetFade, 
                    logger=self._logger, 
                    broadcastFunction=self.broadcastFunction, 
                    area=self, 
                    dynetControl=self._dynetControl
                )
        if defaultPresets:
            for presetValue in defaultPresets:
                if int(presetValue) not in self.preset:
                    preset = defaultPresets[presetValue]
                    presetName = preset[CONF_NAME] if preset[CONF_NAME] else None
                    presetFade = preset[CONF_FADE] if preset[CONF_FADE] else fade
                    self.preset[int(presetValue)] = DynalitePreset(
                        name=presetName, 
                        value=presetValue, 
                        fade=presetFade, 
                        logger=self._logger, 
                        broadcastFunction=self.broadcastFunction, 
                        area=self, 
                        dynetControl=self._dynetControl
                    )
        if areaChannels:
            for channelValue in areaChannels:
                if (int(channelValue) >=1) and (int(channelValue)<=255):
                    channel = areaChannels[channelValue]
                    name = channel[CONF_NAME] if channel and (CONF_NAME in channel) else 'Channel ' + channelValue
                    fade = channel[CONF_FADE] if channel and (CONF_FADE in channel) else self.fade # if no fade provided, use the fade of the area
                    self.channel[int(channelValue)] = DynaliteChannel(
                        name=name, 
                        value=channelValue, 
                        fade=fade, 
                        logger=self._logger, 
                        broadcastFunction=self.broadcastFunction, 
                        area=self, 
                        dynetControl=self._dynetControl
                    )
                    self._logger.debug("added area %s channel %s name %s" % (self.name, channelValue, name) )
                else:
                    self._logger.error("illegal channel value area %s channel %s" % (self.name, channelValue))
        else:
            self.channel = {}
        self.requestPreset() # ask for the initial preset
   

    def presetOn(self, preset, sendDynet=True, sendMQTT=True, autodiscover=False):
        if hasattr(self, 'onPreset'):
            if self.onPreset == preset:
                self.state = self._onName
        else:
            self.state = self._offName
        if preset not in self.preset:
            if not autodiscover:
                return
            self.preset[preset] = DynalitePreset(
                value=preset, 
                fade=self.fade, 
                logger=self._logger, 
                broadcastFunction=self.broadcastFunction, 
                area=self, 
                dynetControl=self._dynetControl
            )
        self.preset[preset].turnOn(sendDynet=sendDynet, sendMQTT=sendMQTT)

    def presetOff(self, preset, sendDynet=True, sendMQTT=True): # XXX TODO check if this is used anywhere. generally presets cannot be turned off
        if preset not in self.preset:
            return # XXX if we want it to auto-register presets need to fix race condition
            self.preset[preset] = DynalitePreset(
                value=preset, 
                fade=self.fade, 
                logger=self._logger, 
                broadcastFunction=self.broadcastFunction, 
                area=self, 
                dynetControl=self._dynetControl
            )
        else: # this still has a bug that the preset won't be selected when chosen. Need a better fix for the race XXX
            self.preset[preset].turnOff(sendDynet=sendDynet, sendMQTT=sendMQTT)
        
    def requestPreset(self):
        self._dynetControl.request_area_preset(self.value)
        
    def setChannelLevel(self, channel, level, autodiscover=False):
        if channel not in self.channel:
            if not autodiscover:
                return
            self.channel[channel] = DynaliteChannel(
                value=channel, 
                fade=self.fade, 
                logger=self._logger, 
                broadcastFunction=self.broadcastFunction, 
                area=self, 
                dynetControl=self._dynetControl
            )
        self.channel[channel].setLevel(level)

    def requestChannelLevel(self, channel):
        self._dynetControl.request_channel_level(area=self.value, channel=channel)

    def requestAllChannelLevels(self):
        for channel in self.channel:
            self.requestChannelLevel(channel) 

class Dynalite(object):

    def __init__(self, config=None, loop=None, logger=None):
        self.loop = loop if loop else asyncio.get_event_loop()
        self._logger = logger if logger else logging.getLogger(__name__)
        self._config = DynaliteConfig(config=config)
        logging.basicConfig(level=self._config.log_level,
                            format=self._config.log_formatter)

        self._configured = False
        self._autodiscover = False
        self._listeners = []

        self.devices = {
            CONF_AREA: {}
        }

        self._dynet = None
        self.control = None

    def start(self):
        self.loop.create_task(self._start())

    @asyncio.coroutine
    def _start(self):
        self._dynet = Dynet(host=self._config.host, port=self._config.port,
                            loop=self.loop, broadcaster=self.processTraffic, onConnect=self._connected, onDisconnect=self._disconnection)
        self.control = DynetControl(
            self._dynet, self.loop, areaDefinition=self.devices[CONF_AREA])
        self.connect() # connect asynchronously. not needed to register devices
        if not self._configured:
            self.loop.create_task(self._configure())

    def connect(self):
        self.loop.create_task(self._connect())

    @asyncio.coroutine
    def _connect(self):
        self._dynet.connect()

    @asyncio.coroutine
    def _connected(self, dynet=None, transport=None):
        self.broadcast(Event(eventType='connected', data={}))

    @asyncio.coroutine
    def _disconnection(self, dynet=None):
        self.broadcast(Event(eventType='disconnected', data={}))
        self.connect()

    def processTraffic(self, event):
        self.loop.create_task(self._processTraffic(event))

    @asyncio.coroutine
    def _processTraffic(self, event):
        # The logic here is:
        # - new area is created - ask for the current preset
        # - preset selected - turn the preset on but don't send it as a command
        # - new channel is created - ask for the current level
        # - channel update - update the level and if it is fading (actual != target), schedule a timer to ask again
        # - channel set command - request current level (may not be the target because of fade)
        areaValue = event.data['area']
        if areaValue not in self.devices[CONF_AREA]:
            self._logger.debug("Update from unknown area: %s" % event.toJson)
            if self._autodiscover:
                areaName = "Area " + str(areaValue)
                areaFade = self._config.default[CONF_FADE] if CONF_FADE in self._config.default else 2
                self.devices[CONF_AREA][areaValue] = DynaliteArea( 
                    name=areaName, 
                    value=areaValue, 
                    fade=areaFade, 
                    logger=self._logger, 
                    broadcastFunction=self.broadcast, 
                    dynetControl=self.control
                )
            else:
                return # No need to do anything if the area is not defined and we do not have autodiscovery
        curArea = self.devices[CONF_AREA][areaValue]

        if event.eventType in ['NEWPRESET', 'NEWCHANNEL']:
            self._logger.error(event.eventType + " in _processTraffic - we should not get here")
        elif event.eventType == 'PRESET':
            curArea.presetOn(event.data['preset'], sendDynet=False, sendMQTT=False, autodiscover=self._autodiscover)
        elif event.eventType == 'CHANNEL':
            if event.data['action'] == 'report':
                curArea.setChannelLevel( event.data['channel'], (255-event.data['actual_level']) / 254.0, self._autodiscover )
                if event.data['actual_level'] != event.data['target_level']:
                    self._logger.debug("area=%s channel=%s actual_level=%s target_level=%s setting timer" % (areaValue, event.data['channel'], event.data['actual_level'], event.data['target_level']) )
                    self.loop.call_later(self._polltimer, curArea.requestChannelLevel, event.data['channel'])
            elif event.data['action'] == 'cmd':
                target_level = False
                if 'preset' in event.data:
                    try:
                        target_level = curArea.channel[event.data['channel']].presets[str(event.data['preset'])]
                    except KeyError:
                        pass
                if 'target_level' in event.data:
                    target_level = (255 - event.data['target_level']) / 254.0
                if target_level: # check if this is relevant for "ALL"
                    if event.data['channel'] == 'ALL':
                        raise Exception("CHANNEL event with ALL and target_level - should never happen") # XXX find a better way to handle it
                    curArea.setChannelLevel( event.data['channel'], target_level, self._autodiscover )    
                if event.data['channel'] == 'ALL':
                    curArea.requestAllChannelLevels()
                else:
                    curArea.requestChannelLevel(event.data['channel'])
            else:
                self._logger.warning("CHANNEL command unknown cmd: %s" % event.toJson)
        else:
            self._logger.debug("Upknown event type: %s" % event.toJson)
        # First handle, and then broadcast so broadcast receivers have updated device levels and presets
        self.broadcast(event)

    def broadcast(self, event):
        self.loop.create_task(self._broadcast(event))

    @asyncio.coroutine
    def _broadcast(self, event):
        for listenerFunction in self._listeners:
            listenerFunction.update(event=event, dynalite=self)

    @asyncio.coroutine
    def _configure(self):
        self._autodiscover = self._config.autodiscover
        self._polltimer = self._config.polltimer
        for areaValue in self._config.area:
            areaName = self._config.area[areaValue][CONF_NAME] if CONF_NAME in self._config.area[areaValue] else None
            areaPresets = self._config.area[areaValue][CONF_PRESET] if CONF_PRESET in self._config.area[areaValue] else {
            }
            areaFade = self._config.area[areaValue][CONF_FADE] if CONF_FADE in self._config.area[areaValue] else None
            if areaFade is None:
                areaFade = self._config.default[CONF_FADE] if CONF_FADE in self._config.default else 2
            areaFade = float(areaFade)
            areaChannels = self._config.area[areaValue][CONF_CHANNEL] if CONF_CHANNEL in self._config.area[areaValue] else None
            if CONF_NODEFAULT in self._config.area[areaValue] and self._config.area[areaValue][CONF_NODEFAULT] == True:
                defaultPresets = None
            else:
                defaultPresets = self._config.preset

            self._logger.debug(
                "Generating Area '%d/%s' with a default fade of %f" % (int(areaValue), areaName, areaFade))
            self.devices[CONF_AREA][int(areaValue)] = DynaliteArea(
                name=areaName, value=areaValue, fade=areaFade, areaPresets=areaPresets, areaChannels=areaChannels, defaultPresets=defaultPresets, logger=self._logger, broadcastFunction=self.broadcast, dynetControl=self.control)
        self._configured = True

    def state(self):
        self.loop.create_task(self._state())

    @asyncio.coroutine
    def _state(self):
        for areaValue in self.devices[CONF_AREA]:
            area = self.devices[CONF_AREA][areaValue]
            for presetValue in area.preset:
                preset = area.preset[presetValue]
                presetState = 'ON' if preset.active else 'OFF'
                broadcastData = {
                    'area': area.value,
                    'preset': preset.value,
                    'name': area.name + ' ' + preset.name,
                    'state': presetState
                }
                self.broadcast(
                    Event(eventType='newpreset', data=broadcastData))
                if preset.active:
                    self.broadcast(
                        Event(eventType='preset', data=broadcastData))
            self.control.areaReqPreset(area.value)

    def addListener(self, listenerFunction=None):
        broadcaster = Broadcaster(
            listenerFunction=listenerFunction, loop=self.loop, logger=self._logger)
        self._listeners.append(broadcaster)
        return broadcaster
