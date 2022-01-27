# Usage:

```
git clone git@github.com:sevenever/chrome-native-message-hub.git

cd chrome-native-message-hub/host
```

### on macos
```
sed -i '' "s#/home/seven#${HOME}#g" com.sevenever.chrome_native_message_hub.json
ln -s `pwd`/com.sevenever.chrome_native_message_hub.json ~/Library/Application\ Support/Google/Chrome/NativeMessagingHosts
```

### on linux
```
sed -i "s#/home/seven#${HOME}#g" com.sevenever.chrome_native_message_hub.json
ln -s `pwd`/com.sevenever.chrome_native_message_hub.json ~/.config/google-chrome/NativeMessagingHosts
```

## restart chrome
