/* starrco-profile.js
 * Sets body[data-profile="<name>"] from /api/profile/active on page load
 * and re-applies on profile switches (storage event cross-tab sync).
 *
 * New file -- zero merge surface with upstream. Loaded by index.html inside
 * the existing starrco-patches block so it carries through rebases cleanly.
 *
 * Intentionally self-contained: no dependencies on boot.js or ui.js internals.
 */
(function () {
  'use strict';

  function applyProfile(name) {
    var n = (name || 'default').trim().toLowerCase();
    document.body.dataset.profile = n;
  }

  // Fetch active profile from server and apply.
  function syncProfile() {
    fetch('/api/profile/active')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (data && data.name) applyProfile(data.name);
      })
      .catch(function () { /* no-op -- default stays */ });
  }

  // Apply on DOMContentLoaded (body exists, CSS can match immediately).
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', syncProfile);
  } else {
    syncProfile();
  }

  // Re-sync when another tab switches profile (storage event) or when the
  // profile chip fires a custom event (panels.js emits 'hermes:profilechange'
  // after switchToProfile resolves -- if that event exists, use it; otherwise
  // the storage event is sufficient for cross-tab sync).
  window.addEventListener('storage', function (e) {
    if (e.key === 'hermes-active-profile' && e.newValue) {
      applyProfile(e.newValue);
    }
  });

  // Hook into the profile switch that panels.js performs. After switchToProfile
  // calls the API and updates S.activeProfile, it also updates profileChipLabel.
  // We watch for that DOM mutation as a reliable same-tab signal -- no internal
  // JS coupling needed.
  var chipLabel = document.getElementById('profileChipLabel');
  if (!chipLabel) {
    // Chip is rendered after DOMContentLoaded; wait for it.
    document.addEventListener('DOMContentLoaded', function () {
      chipLabel = document.getElementById('profileChipLabel');
      if (chipLabel) observeChip(chipLabel);
    });
  } else {
    observeChip(chipLabel);
  }

  function observeChip(el) {
    var obs = new MutationObserver(function () {
      var text = el.textContent.trim().toLowerCase();
      if (text) applyProfile(text);
    });
    obs.observe(el, { childList: true, characterData: true, subtree: true });
  }
})();
