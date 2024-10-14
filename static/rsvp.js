document.addEventListener('DOMContentLoaded', function() {
  const yesRadio = document.getElementById('yes');
  const noRadio = document.getElementById('no');
  const guestsInputContainer = document.getElementById('guestsInputContainer');
  const numGuestsInput = document.getElementById('num_guests');

  function toggleGuestsInput() {
      if (yesRadio.checked) {
          guestsInputContainer.style.display = 'flex';
          numGuestsInput.required = true;
      } else {
          guestsInputContainer.style.display = 'none';
          numGuestsInput.required = false;
          numGuestsInput.value = '1';
      }
  }

  yesRadio.addEventListener('change', toggleGuestsInput);
  noRadio.addEventListener('change', toggleGuestsInput);

  // Initial check in case the page is reloaded with a selection already made
  toggleGuestsInput();
});