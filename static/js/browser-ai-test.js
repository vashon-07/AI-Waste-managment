import { pipeline } from "https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.7.2";

let classifier = null;

async function loadModel() {
    console.log("Loading browser AI model...");

    classifier = await pipeline(
        "image-classification",
        "Xenova/waste-classification"
    );

    console.log("Browser AI model loaded!");
}

window.testWasteAI = async function (file) {
    if (!classifier) {
        await loadModel();
    }

    const result = await classifier(file);

    console.log("Prediction:", result);

    return result;
};