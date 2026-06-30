(function () {
  const chatbox = document.getElementById("chatbox");
  if (!chatbox) return;

  window.setInterval(function () {
    const separator = window.location.search ? "&" : "?";
    fetch(window.location.pathname + separator + "_ajax=1")
      .then(function (response) {
        if (!response.ok) return "";
        return response.text();
      })
      .then(function (html) {
        if (html) {
          chatbox.innerHTML = html;
        }
      })
      .catch(function () {});
  }, 4000);
})();
