document.querySelectorAll("[data-phone-input]").forEach((input) => {
  input.addEventListener("input", () => {
    const digits = input.value.replace(/\D/g, "").slice(0, 11);

    if (digits.length <= 3) {
      input.value = digits;
    } else if (digits.length <= 7) {
      input.value = `${digits.slice(0, 3)}-${digits.slice(3)}`;
    } else {
      input.value = `${digits.slice(0, 3)}-${digits.slice(3, 7)}-${digits.slice(7)}`;
    }
  });
});
