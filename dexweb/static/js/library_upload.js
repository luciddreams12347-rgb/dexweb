(function () {
  var fileInput = document.getElementById("upload-files");
  var folderInput = document.getElementById("upload-folder");
  var summary = document.getElementById("upload-selection");
  if (!fileInput || !folderInput || !summary) {
    return;
  }

  function updateSummary() {
    var files = [];
    if (fileInput.files && fileInput.files.length) {
      files = Array.prototype.slice.call(fileInput.files);
    } else if (folderInput.files && folderInput.files.length) {
      files = Array.prototype.slice.call(folderInput.files);
    }
    if (!files.length) {
      summary.textContent = "No files selected.";
      return;
    }
    var folders = {};
    files.forEach(function (file) {
      var parts = (file.webkitRelativePath || file.name || "").split("/");
      if (parts.length > 1) {
        folders[parts[0]] = true;
      }
    });
    var folderNames = Object.keys(folders);
    if (folderNames.length) {
      summary.textContent = files.length + " files selected from folder: " + folderNames.join(", ");
      return;
    }
    summary.textContent = files.length + " file" + (files.length === 1 ? "" : "s") + " selected.";
  }

  fileInput.addEventListener("change", function () {
    if (fileInput.files && fileInput.files.length) {
      folderInput.value = "";
    }
    updateSummary();
  });

  folderInput.addEventListener("change", function () {
    if (folderInput.files && folderInput.files.length) {
      fileInput.value = "";
    }
    updateSummary();
  });
})();
