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

const employeeEditDialog = document.querySelector("#employee-edit-dialog");

if (employeeEditDialog) {
  const editForm = employeeEditDialog.querySelector("#employee-edit-form");
  const nameInput = employeeEditDialog.querySelector("#edit-employee-name");
  const departmentSelect = employeeEditDialog.querySelector("#edit-employee-department");
  const phoneInput = employeeEditDialog.querySelector("#edit-employee-phone");
  const statusSelect = employeeEditDialog.querySelector("#edit-employee-status");
  const deleteButton = employeeEditDialog.querySelector("#edit-employee-delete");

  document.querySelectorAll("[data-employee-edit]").forEach((button) => {
    button.addEventListener("click", () => {
      editForm.action = `/employees/${button.dataset.employeeId}/edit`;
      nameInput.value = button.dataset.employeeName;
      departmentSelect.value = button.dataset.employeeDepartment;
      phoneInput.value = button.dataset.employeePhone;
      statusSelect.value = button.dataset.employeeStatus;
      deleteButton.formAction = `/employees/${button.dataset.employeeId}/delete`;
      deleteButton.onclick = () => confirm(
        `${button.dataset.employeeName}님을 직원 목록에서 삭제할까요? 과거 기록은 유지됩니다.`,
      );
      formatPhoneInput(phoneInput);
      employeeEditDialog.showModal();
      nameInput.focus();
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

  openButton.addEventListener("click", () => confirmSmsDialog.showModal());

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
