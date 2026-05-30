export declare global {
    interface Document {
        webkitFullscreenElement();
        mozFullScreenElement();
        msFullscreenElement();
    }

    interface Window {
        webkitAudioContext: typeof AudioContext;
    }
}
