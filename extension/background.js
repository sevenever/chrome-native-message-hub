!function (global) {
    var hub_name = 'com.sevenever.chrome_native_message_hub';
    var native_message_port = chrome.runtime.connectNative(hub_name);
    native_message_port.onMessage.addListener(function(msg) {
        var port = extensions[msg.extensionId];
        if (port) {
            port.postMessage(msg.message);
        }
    });

    var extensions = {}; // connected extensionId -> port
    chrome.runtime.onConnectExternal.addListener(function (port) {
        var extensionId = port.sender.id;
        extensions[extensionId] = port;
        port.onMessage.addListener(function (message) {
            native_message_port.postMessage({
                extensionId: extensionId,
                message: message
            });
        });
        port.onDisconnect.addListener(function () {
            delete extensions[extensionId];
        });
    })
}(this);
