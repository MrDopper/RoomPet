
//Directly control roomba from the terminal
//Use node roomba.js clean to start the machine
const dorita980 = require("dorita980");

const { ROOMBA_BLID, ROOMBA_PASSWORD, ROOMBA_IP } = process.env;
const command = process.argv[2] || "status";

if (!ROOMBA_BLID || !ROOMBA_PASSWORD || !ROOMBA_IP) {
    console.error("Missing Roomba credentials or IP address.");
    process.exit(1);
}

const robot = new dorita980.Local(
    ROOMBA_BLID,
    ROOMBA_PASSWORD,
    ROOMBA_IP
);

const timeout = setTimeout(() => {
    console.error("Connection timed out.");
    robot.end();
    process.exitCode = 1;
}, 15000);

robot.on("connect", async () => {
    clearTimeout(timeout);
    console.log("Connected to Roomba!");

    try {
        let result;

        switch (command) {
            case "status":
                result = await robot.getBasicMission();
                break;

            case "clean":
                result = await robot.clean();
                break;

            case "stop":
                result = await robot.stop();
                break;

            default:
                console.error("Use: status, clean, or stop");
                process.exitCode = 1;
                return;
        }

        console.log(result);
    } catch (error) {
        console.error("Command failed:", error);
        process.exitCode = 1;
    } finally {
        robot.end();
    }
});

robot.on("offline", () => {
    console.error("Roomba is offline or disconnected.");
});
