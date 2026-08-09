// Service Worker Flashscore Live — Gestion des notifications push en arrière-plan
// Installé sur le domaine pour permettre les notifications même téléphone verrouillé

self.addEventListener('install', (e) => {
    self.skipWaiting();
});

self.addEventListener('activate', (e) => {
    e.waitUntil(clients.claim());
});

// Réception des messages depuis la page principale
self.addEventListener('message', (e) => {
    if (e.data && e.data.type === 'GOAL_NOTIFICATION') {
        const { dom, ext, score_dom, score_ext, league } = e.data.game;
        e.waitUntil(
            self.registration.showNotification(`⚽ BUT ! ${dom} ${score_dom} - ${score_ext} ${ext}`, {
                body: `⭐ Match Favori • ${league}`,
                icon: '/favicon.ico',
                badge: '/favicon.ico',
                tag: e.data.game.id,
                requireInteraction: false,
                vibrate: [200, 100, 200, 100, 400],
                data: { url: self.registration.scope }
            })
        );
    }
});

// Clic sur la notification → ouvre ou refocus l'onglet
self.addEventListener('notificationclick', (e) => {
    e.notification.close();
    e.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
            for (const client of clientList) {
                if (client.url.includes(self.registration.scope) && 'focus' in client) {
                    return client.focus();
                }
            }
            if (clients.openWindow) {
                return clients.openWindow('/');
            }
        })
    );
});
