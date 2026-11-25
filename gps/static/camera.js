"use strict";

const video = document.getElementById("collector-video");
const statusText = document.getElementById("camera-status");
const closeCamera = document.getElementById("camera-stop");
const scanButtons = document.querySelectorAll("[data-camera-field]");
let stream = null;
let generation = 0;

function stopScanner(message) {
  generation += 1;
  if (stream) stream.getTracks().forEach(track => track.stop());
  stream = null;
  video.srcObject = null;
  video.hidden = true;
  closeCamera.hidden = true;
  if (message) statusText.textContent = message;
}

async function openScanner(field) {
  stopScanner();
  const current = generation;
  statusText.textContent = "Solicitando acesso à câmera…";
  closeCamera.hidden = false;
  try {
    const detector = new BarcodeDetector();
    const acquired = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: { facingMode: { ideal: "environment" } },
    });
    if (current !== generation) {
      acquired.getTracks().forEach(track => track.stop());
      return;
    }
    stream = acquired;
    video.srcObject = acquired;
    video.hidden = false;
    await video.play();
    if (current !== generation) return;
    statusText.textContent = "Aponte para o código e mantenha-o no quadro.";

    async function scan() {
      if (current !== generation) return;
      try {
        const results = await detector.detect(video);
        if (current !== generation) return;
        const value = results.find(code => code.rawValue.trim())?.rawValue.trim();
        if (value) {
          if (value.length > 100) {
            stopScanner("Código maior que o limite aceito. Confira a etiqueta.");
            return;
          }
          field.value = value.toUpperCase();
          field.dispatchEvent(new Event("input", { bubbles: true }));
          field.focus();
          field.dispatchEvent(new KeyboardEvent("keydown", {
            key: "Enter", bubbles: true, cancelable: true,
          }));
          stopScanner("Código lido. Confira o produto e a locação antes de registrar.");
          return;
        }
        setTimeout(scan, 160);
      } catch (error) {
        if (current === generation) stopScanner("A leitura falhou. Use o campo de digitação.");
      }
    }
    scan();
  } catch (error) {
    if (current === generation) stopScanner("Câmera indisponível. Digite ou use um leitor externo.");
  }
}

if (!window.isSecureContext || !("BarcodeDetector" in window) || !navigator.mediaDevices?.getUserMedia) {
  scanButtons.forEach(button => { button.disabled = true; });
  statusText.textContent = "Câmera indisponível neste navegador. Digite ou use um leitor externo.";
} else {
  scanButtons.forEach(button => {
    button.addEventListener("click", () => openScanner(document.getElementById(button.dataset.cameraField)));
  });
  closeCamera.addEventListener("click", () => stopScanner("Câmera fechada."));
  window.addEventListener("pagehide", () => stopScanner());
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopScanner("Câmera fechada.");
  });
}
