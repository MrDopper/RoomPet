
const dorita980 = require("dorita980");

console.log("Searching for Roomba e5...");

const timeout = setTimeout(() => {
    console.log("No response after 15 seconds.");
    console.log("Check Wi-Fi and robot power.");
    process.exit(1);
}, 15000);

dorita980.getRobotIP((error, ip) => {
    clearTimeout(timeout);

    if (error) {
        console.error("Discovery error:", error);
        process.exitCode = 1;
    } else if (ip) {
        console.log("Roomba found!");
        console.log("IP address:", ip);
    } else {
        console.log("Discovery finished, but no IP was returned.");
    }
});
