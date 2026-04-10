const display = document.getElementById("display");

function appendValue(val) {
  if (display.value === "0") {
    display.value = val;
  } else {
    display.value += val;
  }
}

function clearDisplay() {
  display.value = "0";
}

function deleteLast() {
  display.value = display.value.slice(0, -1) || "0";
}

function calculate() {
  try {
    display.value = eval(display.value);
  } catch {
    display.value = "Error";
  }
}
