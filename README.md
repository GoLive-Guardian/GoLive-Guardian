# GoLive Guardian
GoLive Guardian(GG) was created for Asphalt Legends Unite discord community but is not limited to it.
GG assists you automatically manage Go Lives streams in Voice Channels in your discord server.

Basically, each channel's Stream limitation is set to 1 (It can be changed - Future feature)

## 1. How it works
Potential Streamer - A member try to Go Live stream in a voice channel - may encounter situations below:

### (1) Not Exceeding Stream limit in the channel
* Bot does nothing and Potential Streamers are allowed to proceed their stream.

### (2) Exceeding Stream limit in the channel
* Occurs when the Bot is already running
  * Bot tries to kick Potential Streamer from the channel (Bot MUST have Move Members permission).
    * If failed to kick, bot tries to send warn message to channel with mod mention(mention is exclusive feature for ALU Server).
  * After the streamer being kicked, A warn message that contains stream info about the channel will be sent.
    * This message will be removed by clicking button by the streamer or Manage Message permission holder.

* Occurred before the Bot runs or the channel had not handled before
  * After starting (or setting) up, Bot detects all channels that exceed each channel's stream limit (Conflict Channels).
  * Bot sends messages that request streamers to resolve conflict in 3 minutes to all Conflict Channels.
    * If the conflict isn't resolved until expiration time, then all streamers will be kicked from the channel.
    * If a channel's stream count backs to normal, then considered as conflict resolved.

## 2. Commands
All commands can be run by members who have **Manage Channels** and are slash commands.

### - Setup
First, you may need to run `/setup` command to determine voice channels to let bot watch. 
Then, you can see a menu and buttons. If a channel is public, then setup message will be shown for you.

#### (1) Menu
Select voice channels to watch from one to five (it could be increased). 
If the bot doesn't have proper permission for channels, there will be a permission sync request message.
After being synced, success channels and failed channels (with reason) are shown with a embed message.
* If you have failed channels, consider to edit permission of channels by hand and retry, or do not select that channel again.

#### (2) Buttons
* **Watch Channels** : Determine to watch channels or not. Setup message will show 'Yes', if you want to watch those channels, or 'No'.
* **Config Channels** : Put the stream limit for each channel. Currently, it is limited to 1.
* **Save** : Save your setup.
* **Revert** : Go back to your initial setup (Not 'reset').
* **Cancel** : Cancel your setup.

### - Status
A message that shows current stream status for each channel will be sent. This message isn't automatically updated. 

* Conflict Streamer - Please Refer 1-(2). Exceeding Stream limit in the channel
* Streamers - You can see streamers and their stream starting time. Starting time may be shown to 'Unknown' when bot fails to catch the time.

### - Reset
* Reset your setup. All Conflicts across channels in your setup will be automatically terminated.

## 3. Examples
1. [GoLive Guardian Example 1](https://youtu.be/4kNAF0HLvxM)
2. [GoLive Guardian Example 2](https://youtu.be/EnDWfOiYDxM)
3. [GoLive Guardian Example 3](https://youtu.be/HnF286xIcTM)