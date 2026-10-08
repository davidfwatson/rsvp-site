(() => {
  const config = JSON.parse(document.getElementById('analytics-config').textContent);
  document.body.append(document.getElementById('analytics-choice-template').content.cloneNode(true));
  const choice = document.getElementById('analytics-choice');
  let loaded = false;
  function allow() {
    if (loaded || navigator.globalPrivacyControl || navigator.doNotTrack === '1') return;
    loaded = true;
    window.dataLayer = window.dataLayer || [];
    window.gtag = function(){window.dataLayer.push(arguments);};
    window.gtag('js', new Date());
    // Explicitly replace URL, title and referrer before any analytics events.
    // Enhanced measurement must also be disabled in this GA property's stream.
    const location = window.location.origin + config.path;
    window.gtag('set', {page_location:location,page_referrer:'',page_title:'PartyMail'});
    window.gtag('config',config.id,{send_page_view:false,allow_google_signals:false,allow_ad_personalization_signals:false});
    window.gtag('event','page_view',{page_location:location,page_referrer:'',page_title:'PartyMail'});
    const script = document.createElement('script');script.async = true;script.src='https://www.googletagmanager.com/gtag/js?id='+encodeURIComponent(config.id);document.head.appendChild(script);
  }
  let consent;
  try {consent=localStorage.getItem('partymail-analytics');}catch{}
  if(navigator.globalPrivacyControl || navigator.doNotTrack==='1')return;
  if(consent==='allow')allow();else if(consent!=='decline')choice.hidden=false;
  document.getElementById('analytics-allow').addEventListener('click',()=>{try{localStorage.setItem('partymail-analytics','allow');}catch{}choice.hidden=true;allow();});
  document.getElementById('analytics-decline').addEventListener('click',()=>{try{localStorage.setItem('partymail-analytics','decline');}catch{}choice.hidden=true;});
})();
