(function() {
    var endpoint = '/api/track';

    function getDevice() {
        return window.matchMedia && window.matchMedia('(max-width: 760px)').matches ? 'mobile' : 'desktop';
    }

    function cleanText(text) {
        return (text || '').replace(/\s+/g, ' ').trim().slice(0, 80);
    }

    function send(payload) {
        var body = JSON.stringify(Object.assign({
            page: location.pathname,
            path: location.pathname + location.search,
            title: document.title,
            referrer: document.referrer,
            device: getDevice()
        }, payload));

        if (navigator.sendBeacon) {
            try {
                var ok = navigator.sendBeacon(endpoint, new Blob([body], { type: 'application/json' }));
                if (ok) return;
            } catch (err) {}
        }

        fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: body,
            keepalive: true
        }).catch(function() {});
    }

    function featureName(link) {
        if (!link) return '';
        if (link.dataset && link.dataset.track) return cleanText(link.dataset.track);
        var named = link.querySelector('.name, h3, h2, span');
        return cleanText(named ? named.textContent : link.textContent);
    }

    document.addEventListener('DOMContentLoaded', function() {
        send({ type: 'page_view' });
    });

    document.addEventListener('click', function(event) {
        var link = event.target.closest && event.target.closest('a[href]');
        if (!link) return;

        var href = link.getAttribute('href') || '';
        var isToolEntry = link.classList.contains('tool-card') ||
            link.classList.contains('resource-card') ||
            link.classList.contains('quick-link');

        if (!isToolEntry && !href.match(/^pages\//)) return;

        send({
            type: 'feature_click',
            feature: featureName(link) || href,
            href: href
        });
    });
})();
