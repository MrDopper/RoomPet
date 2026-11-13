
//Directly control roomba from the terminal
//Use node roomba.js clean to start the machine


const dorita980 = require("dorita980");

const { ROOMBA_BLID, ROOMBA_PASSWORD, ROOMBA_IP } = process.env;
const command = process.argv[2] || "status";

if (!ROOMBA_BLID || !ROOMBA_PASSWORD || !ROOMBA_IP) {
    console.error("Missing Roomba credentials.");
    process.exit(1);
}

if (!["status", "clean", "stop", "dock"].includes(command)) {
    console.error("Use: status, clean, stop, or dock");
    process.exit(1);
}

const robot = new dorita980.Local(
    ROOMBA_BLID,
    ROOMBA_PASSWORD,
    ROOMBA_IP
);

let finished = false;

const timeout = setTimeout(() => {
    finish(new Error("Connection timed out"));
}, 15000);

function finish(error, result) {
    if (finished) return;
    finished = true;
    clearTimeout(timeout);

    if (error) {
        console.error("Roomba error:", error.message || error);
        process.exitCode = 1;
    } else {
        console.log(result);
    }

    robot.end();
}

robot.on("connect", async () => {
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

            case "dock":
                await robot.stop();
                result = await robot.dock();
                break;
        }

        finish(null, result);

    } catch (error) {
        finish(error);
    }
});

robot.on("offline", () => {
    finish(new Error("Roomba disconnected"));
});
