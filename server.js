const express = require("express");
const axios = require("axios");
const cors = require("cors");

const app = express();
app.use(cors());

// Proxy route
app.get("/proxy", async (req, res) => {
    try {
        const url = req.query.url;

        if (!url) {
            return res.status(400).send("No URL provided");
        }

        const response = await axios.get(url, {
            responseType: "stream",
            headers: {
                "User-Agent": "Mozilla/5.0"
            }
        });

        res.setHeader("Content-Type", "application/vnd.apple.mpegurl");

        response.data.pipe(res);

    } catch (err) {
        console.log(err.message);
        res.status(500).send("Stream error");
    }
});

app.listen(3000, () => {
    console.log("CORS Proxy running on http://localhost:3000");
});
