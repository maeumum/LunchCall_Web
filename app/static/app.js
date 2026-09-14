const formatPhoneInput = (input) => {
  const digits = input.value.replace(/\D/g, "").slice(0, 11);

  if (digits.length <= 3) {
    input.value = digits;
  } else if (digits.length <= 7) {
    input.value = `${digits.slice(0, 3)}-${digits.slice(3)}`;
  } else {
    input.value = `${digits.slice(0, 3)}-${digits.slice(3, 7)}-${digits.slice(7)}`;
  }
};

document.querySelectorAll("[data-phone-input]").forEach((input) => {
  input.addEventListener("input", () => {
    formatPhoneInput(input);
  });
});

const dashboardDate = document.querySelector("[data-dashboard-date]");

if (dashboardDate) {
  const renderedDate = dashboardDate.dataset.dashboardDate;
  const rolloverNotice = document.querySelector("[data-date-rollover-notice]");
  let isReloadingForNewDate = false;

  const currentKoreanDate = () => {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: "Asia/Seoul",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).formatToParts(new Date());
    const values = Object.fromEntries(parts.map(({ type, value }) => [type, value]));
    return `${values.year}-${values.month}-${values.day}`;
  };

  const refreshWhenDateChanges = () => {
    if (isReloadingForNewDate || currentKoreanDate() === renderedDate) return;
    isReloadingForNewDate = true;
    if (rolloverNotice) rolloverNotice.hidden = false;
    window.setTimeout(() => window.location.reload(), 500);
  };

  window.setInterval(refreshWhenDateChanges, 30000);
  window.addEventListener("focus", refreshWhenDateChanges);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") refreshWhenDateChanges();
  });
}

const prepareDialog = (dialog) => {
  dialog.addEventListener("close", () => {
    const trigger = dialog.returnFocusTarget;
    if (trigger?.isConnected) trigger.focus();
    dialog.returnFocusTarget = null;
  });
};

const openDialog = (dialog, trigger, initialFocus) => {
  dialog.returnFocusTarget = trigger;
  dialog.showModal();
  initialFocus?.focus();
};

const employeeEditDialog = document.querySelector("#employee-edit-dialog");

if (employeeEditDialog) {
  const editForm = employeeEditDialog.querySelector("#employee-edit-form");
  const nameInput = employeeEditDialog.querySelector("#edit-employee-name");
  const departmentSelect = employeeEditDialog.querySelector("#edit-employee-department");
  const phoneInput = employeeEditDialog.querySelector("#edit-employee-phone");
  const statusSelect = employeeEditDialog.querySelector("#edit-employee-status");
  const deleteButton = employeeEditDialog.querySelector("#edit-employee-delete");
  const deleteDialog = document.querySelector("#employee-delete-dialog");
  const deleteForm = deleteDialog.querySelector("#employee-delete-form");
  const deleteName = deleteDialog.querySelector("[data-employee-delete-name]");
  const deleteCancelButton = deleteDialog.querySelector(
    ".confirm-modal-actions [data-employee-delete-close]",
  );
  prepareDialog(employeeEditDialog);
  prepareDialog(deleteDialog);

  document.querySelectorAll("[data-employee-edit]").forEach((button) => {
    button.addEventListener("click", () => {
      editForm.action = `/employees/${button.dataset.employeeId}/edit`;
      nameInput.value = button.dataset.employeeName;
      departmentSelect.value = button.dataset.employeeDepartment;
      phoneInput.value = button.dataset.employeePhone;
      statusSelect.value = button.dataset.employeeStatus;
      deleteForm.action = `/employees/${button.dataset.employeeId}/delete`;
      deleteName.textContent = button.dataset.employeeName;
      formatPhoneInput(phoneInput);
      openDialog(employeeEditDialog, button, nameInput);
      nameInput.select();
    });
  });

  employeeEditDialog.querySelectorAll("[data-modal-close]").forEach((button) => {
    button.addEventListener("click", () => employeeEditDialog.close());
  });

  employeeEditDialog.addEventListener("click", (event) => {
    if (event.target === employeeEditDialog) {
      employeeEditDialog.close();
    }
  });

  deleteButton.addEventListener("click", () => {
    openDialog(deleteDialog, deleteButton, deleteCancelButton);
  });

  deleteDialog.querySelectorAll("[data-employee-delete-close]").forEach((button) => {
    button.addEventListener("click", () => deleteDialog.close());
  });

  deleteDialog.addEventListener("click", (event) => {
    if (event.target === deleteDialog) {
      deleteDialog.close();
    }
  });
}

const employeeSearchInput = document.querySelector("[data-employee-search]");

if (employeeSearchInput) {
  const searchForm = document.querySelector("[data-employee-search-form]");
  const departmentFilter = document.querySelector("[data-employee-department-filter]");
  const statusFilter = document.querySelector("[data-employee-status-filter]");
  const employeeRows = Array.from(document.querySelectorAll("[data-employee-row]"));
  const resultCount = document.querySelector("[data-employee-result-count]");
  const noResultsRow = document.querySelector("[data-employee-no-results]");

  const filterEmployees = () => {
    const query = employeeSearchInput.value.trim().toLocaleLowerCase("ko-KR");
    const department = departmentFilter.value;
    const status = statusFilter.value;
    let visibleCount = 0;

    employeeRows.forEach((row) => {
      const searchText = row.dataset.searchText.toLocaleLowerCase("ko-KR");
      const matchesQuery = searchText.includes(query);
      const matchesDepartment = !department || row.dataset.department === department;
      const matchesStatus = !status || row.dataset.status === status;
      const isVisible = matchesQuery && matchesDepartment && matchesStatus;
      row.hidden = !isVisible;
      if (isVisible) visibleCount += 1;
    });

    const hasFilter = query || department || status;
    resultCount.textContent = hasFilter
      ? `검색 결과 ${visibleCount}명`
      : `전체 ${employeeRows.length}명`;
    noResultsRow.hidden = visibleCount !== 0;
  };

  employeeSearchInput.addEventListener("input", filterEmployees);
  employeeSearchInput.addEventListener("compositionend", filterEmployees);
  departmentFilter.addEventListener("change", filterEmployees);
  statusFilter.addEventListener("change", filterEmployees);
  searchForm.addEventListener("submit", (event) => {
    event.preventDefault();
    filterEmployees();
  });
}

const mealSearchInput = document.querySelector("[data-meal-search]");

if (mealSearchInput) {
  const mealSearchForm = document.querySelector("[data-meal-search-form]");
  const mealFilterButtons = Array.from(
    document.querySelectorAll("[data-meal-filter-value]"),
  );
  const mealEmployeeRows = Array.from(
    document.querySelectorAll("[data-meal-employee]"),
  );
  const mealResultCount = document.querySelector("[data-meal-result-count]");
  const mealNoResults = document.querySelector("[data-meal-no-results]");
  let activeMealFilter = "ALL";

  const filterMealEmployees = () => {
    const query = mealSearchInput.value.trim().toLocaleLowerCase("ko-KR");
    let visibleCount = 0;

    mealEmployeeRows.forEach((row) => {
      const searchText = row.dataset.searchText.toLocaleLowerCase("ko-KR");
      const matchesQuery = searchText.includes(query);
      const matchesStatus =
        activeMealFilter === "ALL" || row.dataset.mealStatus === activeMealFilter;
      const isVisible = matchesQuery && matchesStatus;
      row.hidden = !isVisible;
      if (isVisible) visibleCount += 1;
    });

    const hasFilter = query || activeMealFilter !== "ALL";
    mealResultCount.textContent = hasFilter
      ? `검색 결과 ${visibleCount}명`
      : `전체 ${mealEmployeeRows.length}명`;
    mealNoResults.hidden = visibleCount !== 0;
  };

  mealSearchInput.addEventListener("input", filterMealEmployees);
  mealSearchInput.addEventListener("compositionend", filterMealEmployees);
  mealSearchForm.addEventListener("submit", (event) => {
    event.preventDefault();
    filterMealEmployees();
  });

  mealFilterButtons.forEach((button) => {
    button.addEventListener("click", () => {
      activeMealFilter = button.dataset.mealFilterValue;
      mealFilterButtons.forEach((filterButton) => {
        const isActive = filterButton === button;
        filterButton.classList.toggle("active", isActive);
        filterButton.setAttribute("aria-pressed", String(isActive));
      });
      filterMealEmployees();
    });
  });
}

const confirmSmsDialog = document.querySelector("#confirm-sms-dialog");

if (confirmSmsDialog) {
  const openButton = document.querySelector("[data-confirm-sms-open]");
  const confirmForm = confirmSmsDialog.querySelector("[data-confirm-sms-form]");
  const submitButton = confirmSmsDialog.querySelector("[data-confirm-sms-submit]");
  const cancelButton = confirmSmsDialog.querySelector(
    ".confirm-modal-actions [data-confirm-sms-close]",
  );
  prepareDialog(confirmSmsDialog);

  if (openButton.dataset.confirmTimeLocked === "true") {
    const waitSeconds = Number(openButton.dataset.confirmWaitSeconds || 0);
    const unlockAt = Date.now() + waitSeconds * 1000;
    const timeNotice = document.querySelector("[data-confirm-time-notice]");

    const updateConfirmationTime = () => {
      const remainingSeconds = Math.max(0, Math.ceil((unlockAt - Date.now()) / 1000));
      if (remainingSeconds === 0) {
        openButton.dataset.confirmTimeLocked = "false";
        if (openButton.dataset.confirmPermanentlyBlocked !== "true") {
          openButton.disabled = false;
        }
        if (timeNotice) {
          timeNotice.classList.remove("locked");
          timeNotice.textContent = "지금부터 최종 확정할 수 있습니다.";
        }
        return true;
      }

      const hours = Math.floor(remainingSeconds / 3600);
      const minutes = Math.floor((remainingSeconds % 3600) / 60);
      const seconds = remainingSeconds % 60;
      const remainingText = [
        hours ? `${hours}시간` : "",
        minutes ? `${minutes}분` : "",
        `${seconds}초`,
      ].filter(Boolean).join(" ");
      if (timeNotice) {
        timeNotice.textContent = `한국시간 오전 9:50까지 ${remainingText} 남았습니다.`;
      }
      return false;
    };

    if (!updateConfirmationTime()) {
      const confirmationTimer = window.setInterval(() => {
        if (updateConfirmationTime()) window.clearInterval(confirmationTimer);
      }, 1000);
    }
  }

  openButton.addEventListener("click", () => {
    openDialog(confirmSmsDialog, openButton, cancelButton);
  });

  confirmSmsDialog.querySelectorAll("[data-confirm-sms-close]").forEach((button) => {
    button.addEventListener("click", () => confirmSmsDialog.close());
  });

  confirmSmsDialog.addEventListener("click", (event) => {
    if (event.target === confirmSmsDialog) {
      confirmSmsDialog.close();
    }
  });

  confirmForm.addEventListener("submit", () => {
    submitButton.disabled = true;
    submitButton.textContent = "전송 중...";
  });
}

const smsRetryDialog = document.querySelector("#sms-retry-dialog");

if (smsRetryDialog) {
  const openButton = document.querySelector("[data-sms-retry-open]");
  const cancelButton = smsRetryDialog.querySelector(
    ".confirm-modal-actions [data-sms-retry-close]",
  );
  prepareDialog(smsRetryDialog);

  openButton.addEventListener("click", () => {
    openDialog(smsRetryDialog, openButton, cancelButton);
  });

  smsRetryDialog.querySelectorAll("[data-sms-retry-close]").forEach((button) => {
    button.addEventListener("click", () => smsRetryDialog.close());
  });

  smsRetryDialog.addEventListener("click", (event) => {
    if (event.target === smsRetryDialog) {
      smsRetryDialog.close();
    }
  });
}

document.querySelectorAll("[data-history-open]").forEach((button) => {
  const dialog = document.querySelector(`#${button.dataset.historyOpen}`);
  if (!dialog) return;

  prepareDialog(dialog);
  const closeButton = dialog.querySelector("[data-history-close]");
  button.addEventListener("click", () => openDialog(dialog, button, closeButton));
  dialog.querySelectorAll("[data-history-close]").forEach((closeButton) => {
    closeButton.addEventListener("click", () => dialog.close());
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
});

const smsSettingsPreview = document.querySelector("[data-sms-preview]");

if (smsSettingsPreview) {
  const companyInput = document.querySelector("[data-sms-company]");
  const recipientInput = document.querySelector("[data-sms-recipient]");
  const templateInput = document.querySelector("[data-sms-template]");
  const messagePreview = document.querySelector("[data-sms-preview-message]");
  const recipientPreview = document.querySelector("[data-sms-preview-recipient]");
  const lengthPreview = document.querySelector("[data-sms-length]");

  const updateSmsPreview = () => {
    const message = templateInput.value
      .replaceAll("{company_name}", companyInput.value.trim() || "회사명")
      .replaceAll("{date}", smsSettingsPreview.dataset.previewDate)
      .replaceAll("{meal_count}", "17")
      .replaceAll("{absent_count}", "3");
    messagePreview.textContent = message;
    recipientPreview.textContent = recipientInput.value || "수신 번호 미입력";
    lengthPreview.textContent = `${message.length}자`;
  };

  [companyInput, recipientInput, templateInput].forEach((input) => {
    input.addEventListener("input", updateSmsPreview);
  });
  updateSmsPreview();
}

document.querySelectorAll('form[method="post"]:not([data-confirm-sms-form])').forEach((form) => {
  form.addEventListener("submit", (event) => {
    if (event.defaultPrevented) return;
    if (form.dataset.submitting === "true") {
      event.preventDefault();
      return;
    }

    form.dataset.submitting = "true";
    form.setAttribute("aria-busy", "true");
    form.querySelectorAll('button[type="submit"], input[type="submit"]').forEach((button) => {
      button.disabled = true;
    });

    const submitter = event.submitter;
    if (submitter?.dataset.submittingText) {
      submitter.textContent = submitter.dataset.submittingText;
    }
  });
});
