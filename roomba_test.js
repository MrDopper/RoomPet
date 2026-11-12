const dorita980 = require("dorita980");

const robot = new dorita980.Local(
    process.env.ROOMBA_BLID,
    process.env.ROOMBA_PASSWORD,
    process.env.ROOMBA_IP
);

robot.on("connect", async () => {
    try {
        const state = await robot.getRobotState();
        console.log("Roomba connected!");
        console.log(state);
    } catch (error) {
        console.error("Roomba error:", error);
    } finally {
        robot.end();
    }
});

robot.on("offline", () => {
    console.error("Roomba disconnected");
});
