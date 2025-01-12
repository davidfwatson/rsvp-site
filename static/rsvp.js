document.addEventListener('DOMContentLoaded', function() {
  const yesRadio = document.getElementById('yes');
  const noRadio = document.getElementById('no');
  const guestsInputContainer = document.getElementById('guestsInputContainer');
  const numAdultsInput = document.getElementById('num_adults');
  const numChildrenInput = document.getElementById('num_children');

  function toggleGuestsInput() {
      if (yesRadio.checked) {
          guestsInputContainer.style.display = 'flex';
          numAdultsInput.required = true;
          numChildrenInput.required = true;
      } else {
          guestsInputContainer.style.display = 'none';
          numAdultsInput.required = false;
          numChildrenInput.required = false;
          numAdultsInput.value = '1';
          numChildrenInput.value = '0';
      }
  }

  yesRadio.addEventListener('change', toggleGuestsInput);
  noRadio.addEventListener('change', toggleGuestsInput);

  // Initial check in case the page is reloaded with a selection already made
  toggleGuestsInput();
});