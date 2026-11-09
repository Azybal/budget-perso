<div align="center">

# Budget perso

**Ton budget, connecté à ta banque. Tes données restent chez toi.**

Un logiciel de budget personnel pour Windows, macOS et Linux qui se connecte directement à ta banque,
calcule ton solde de fin de mois, suit tes abonnements et tes crédits, sans aucun serveur ni intermédiaire.

[Télécharger pour Windows](https://github.com/Azybal/budget-perso/releases/latest/download/Budget-perso-Windows.zip) ·
[Télécharger pour macOS](https://github.com/Azybal/budget-perso/releases/latest/download/Budget-perso-macOS.zip) ·
[Télécharger pour Linux](https://github.com/Azybal/budget-perso/releases/latest/download/Budget-perso-Linux.tar.gz)

</div>

> [!IMPORTANT]
> **Pour installer Budget perso**, télécharge le fichier de ton système avec les liens ci-dessus, ou dans la partie
> **Assets** de la [dernière version](https://github.com/Azybal/budget-perso/releases/latest) :
> `Budget-perso-Windows.zip`, `Budget-perso-macOS.zip` ou `Budget-perso-Linux.tar.gz`.
>
> Les liens **Source code (zip / tar.gz)** ajoutés par GitHub contiennent seulement le code du programme, pas l'installateur.

---

## Ce que fait Budget perso

| | |
|---|---|
| **Tableau de bord** | Ton solde actuel en grand, et juste en dessous le solde une fois passées les opérations à venir. Dépenses depuis ta dernière paie, rentrées du mois, abonnements et charges fixes, historique sur 12 mois, dépenses par catégorie, prochains prélèvements. |
| **Solde prévisionnel** | Ce qu'il te restera à la fin du mois : solde actuel − prélèvements et crédits à venir + salaire et rentrées attendues (− dépenses du quotidien estimées, si tu le souhaites). Il affiche aussi la veille de ta paie, pour voir venir un découvert. |
| **Opérations à venir** | Les paiements par carte pas encore débités et les prélèvements programmés, tels que ta banque les annonce. Ils sont pris en compte dans le prévisionnel. |
| **Budget** | Un budget par catégorie (courses, transport, sorties…) qui se remplit tout seul avec tes dépenses : dépensé, reste, barre de progression. Ajoute, renomme ou supprime tes catégories. Clique sur une catégorie pour voir ses dépenses du mois, y ranger d'autres dépenses en un clic et choisir des mots-clés : les prochaines dépenses du même marchand y iront automatiquement. |
| **Mensualités** | Ta liste d'abonnements, de charges fixes et de rentrées régulières : prochain prélèvement, dernier paiement constaté, hausse de prix. Tu peux modifier le prix ou la date, ou résilier. Un abonnement sans paiement depuis plus de 2 mois (délai réglable) passe automatiquement en « arrêté ». |
| **Crédits** | Tes crédits en cours : reste à rembourser, mensualités restantes, fin estimée. Les mensualités sont déduites automatiquement quand elles passent sur ton compte. |
| **On me doit** | L'argent que des proches te doivent, déduit automatiquement quand ils te remboursent. |
| **Dépenses prévues** | Une dépense ou une rentrée exceptionnelle à venir est comptée dans le mois concerné, puis marquée « payée » toute seule. |
| **Ton mois à toi** | Ton mois peut commencer le jour de ta paie (par exemple du 25 au 24). Un salaire versé en avance avant un week-end reste dans le bon mois. |
| **Plusieurs banques** | Connecte plusieurs banques : tous tes comptes sont réunis au même endroit. |
| **Sans banque aussi** | Tu peux importer les relevés CSV ou OFX de n'importe quelle banque. |
| **Alertes** | Une barre de budget passe en orange à l'approche de la limite, et le tableau de bord te prévient si ton solde ou ta fin de mois passe sous le seuil que tu choisis. |
| **Paramètres** | Une fenêtre complète (bouton engrenage) : thème clair, sombre ou automatique, couleur d'accentuation au choix (6 couleurs ou une roue des couleurs), taille du texte, animations, effet de verre, centimes, mode discret qui floute les montants, synchronisation automatique, export de tes opérations en CSV, sauvegarde complète, et une recherche dans tous les réglages. |

L'interface est soignée : style Apple, effet de verre, thème clair ou sombre, et des animations fluides.

---

## Tes données ne quittent jamais ton ordinateur

- **100 % local.** Opérations, soldes, abonnements et crédits sont dans une base de données sur ton ordinateur, dans un dossier accessible uniquement à ton compte.
- **Pas de serveur, pas de compte, pas de pub, pas de statistiques d'utilisation.** Personne d'autre que toi ne voit tes chiffres, pas même l'auteur du logiciel.
- **Connexion directe à ta banque.** Ton ordinateur se connecte lui-même au site de ta banque, sans agrégateur ni intermédiaire.
- **Identifiants dans le trousseau du système** : Gestionnaire d'identification sous Windows, Trousseau sous macOS, GNOME Keyring ou KWallet sous Linux. Ils sont chiffrés, liés à ta session, et jamais écrits dans un fichier. Si ta banque les refuse, ils sont effacés aussitôt pour éviter un blocage de ton accès.
- **Fenêtre privée.** L'interface s'affiche dans une vraie fenêtre (pas ton navigateur) qui ne garde ni cache ni cookies. Le moteur local ne répond qu'à cette fenêtre, grâce à une clé secrète renouvelée à chaque lancement.

**Ce que le logiciel contacte, et rien d'autre :**
- le site de ta banque, pendant une synchronisation ;
- GitHub, pour savoir s'il existe une mise à jour (rien de tes données n'est envoyé) ;
- pendant l'installation seulement : Python, les composants du logiciel et les modules de connexion bancaire.

---

## Banques prises en charge

Crédit Agricole (les 39 caisses régionales) · BNP Paribas · Hello bank! · Société Générale / SG · LCL · Crédit Mutuel · CIC ·
Caisse d'Épargne · Banque Populaire · La Banque Postale · BoursoBank · Fortuneo · BRED · Crédit Coopératif ·
Crédit Mutuel de Bretagne · Crédit Mutuel du Sud-Ouest · AXA Banque · BforBank · Allianz Banque · CCF · N26 ·
Orange Bank · Ma French Bank · La Nef

La double authentification est prise en charge :
- **code reçu par SMS ou carte** : une fenêtre s'ouvre pour le saisir ;
- **validation dans l'appli de ta banque** : le logiciel attend que tu valides sur ton téléphone.

La session est gardée sur ton ordinateur pour que ta banque ne redemande pas un code à chaque fois.

> La connexion bancaire repose sur [Woob](https://woob.tech), un outil libre qui lit le site de ta banque comme tu le ferais.
> Ce n'est pas un accès « officiel » (DSP2) : si une banque modifie son site, la synchronisation peut cesser de fonctionner
> le temps que le module soit corrigé. L'import de relevés CSV ou OFX marche toujours.

---

## Installation

| Système | Fichier | Installation |
|---|---|---|
| **Windows 10 / 11** | [Budget-perso-Windows.zip](https://github.com/Azybal/budget-perso/releases/latest/download/Budget-perso-Windows.zip) | Décompresse, puis double-clique sur `Installer.bat`. Si Windows affiche « Windows a protégé votre ordinateur », clique sur *Informations complémentaires* puis *Exécuter quand même*. |
| **macOS 11 et plus** | [Budget-perso-macOS.zip](https://github.com/Azybal/budget-perso/releases/latest/download/Budget-perso-macOS.zip) | Décompresse, puis fais un clic droit sur `Installer.command` > *Ouvrir*. L'appli s'installe dans le dossier Applications de ton compte. |
| **Linux** (x86_64, ARM64) | [Budget-perso-Linux.tar.gz](https://github.com/Azybal/budget-perso/releases/latest/download/Budget-perso-Linux.tar.gz) | `tar -xzf Budget-perso-Linux.tar.gz && ./Budget-perso-Linux/installer.sh` |

L'installation dure environ 5 minutes. Elle se fait dans ton dossier utilisateur, sans droits administrateur, et installe sa propre copie de Python 3.12 (avec OpenSSL 3) sans toucher au reste de ton système.

Ensuite, ouvre **Budget perso**, clique sur **Connecter ma banque** et laisse-toi guider. Chaque paquet contient un `LISEZMOI.txt` détaillé et un désinstallateur.

---

## Mises à jour automatiques et signées

Au lancement, puis toutes les 6 heures, Budget perso regarde s'il existe une nouvelle version dans les [releases](https://github.com/Azybal/budget-perso/releases) de ce dépôt.

1. Il télécharge le paquet de mise à jour et sa **signature Ed25519**.
2. Il vérifie la signature avec la clé publique intégrée au logiciel. La clé privée correspondante ne quitte jamais l'ordinateur de l'auteur : un paquet modifié, ou publié par quelqu'un d'autre, est refusé.
3. Il refuse aussi tout retour à une version plus ancienne.
4. Il installe la mise à jour en gardant une copie de la version précédente, et la remet automatiquement si quelque chose échoue.
5. Il te propose de redémarrer.

Tes données ne sont jamais touchées par une mise à jour.

---

## Contenu de ce dépôt

| Dossier | Contenu |
|---|---|
| [`programme/`](programme) | Le logiciel lui-même : fenêtre (`BudgetPerso.pyw`), moteur local (`moteur/`), mises à jour signées (`mise_a_jour.py`). C'est ce que contient chaque paquet de mise à jour. |
| [`installateurs/`](installateurs) | Les scripts d'installation et de désinstallation pour Windows, macOS et Linux, avec leur `LISEZMOI.txt`. |

Pour installer, utilise plutôt les fichiers prêts à l'emploi de la [dernière version](https://github.com/Azybal/budget-perso/releases/latest) : ils réunissent le programme et l'installateur.

---

## Comment ça marche

```
┌────────────────────────── ton ordinateur ──────────────────────────┐
│                                                                    │
│  Fenêtre Budget perso ──(clé secrète)──▶ Moteur local (Python)     │
│   interface HTML/CSS                      ├─ base SQLite (données) │
│   pywebview, mode privé                   ├─ calculs : prévision,  │
│                                           │  abonnements, crédits  │
│  Trousseau du système ──(en mémoire)──▶  └─ synchronisation Woob ─┼──▶ site de ta banque
│   identifiants chiffrés                                            │
└────────────────────────────────────────────────────────────────────┘
```

- **Moteur** : Python, bibliothèque standard et SQLite. Il catégorise les opérations, reconnaît les marchands, suit les abonnements et les crédits, et calcule le prévisionnel.
- **Synchronisation** : un processus séparé reçoit les identifiants en mémoire, par un canal privé, se connecte à la banque avec Woob, puis enregistre opérations, soldes et opérations à venir.
- **Interface** : une page HTML/CSS/JS servie uniquement sur `127.0.0.1` et affichée dans une fenêtre native (WebView2 sous Windows, WebKit sous macOS, Qt WebEngine sous Linux).
- **Mises à jour** : releases GitHub signées en Ed25519 et vérifiées avec la bibliothèque `cryptography`.

---

## Questions fréquentes

**Est-ce que l'auteur peut voir mes comptes ?**
Non. Il n'y a aucun serveur : le logiciel tourne entièrement sur ton ordinateur, et rien n'est envoyé ailleurs qu'à ta banque.

**Que se passe-t-il si je perds mon ordinateur ?**
Tes identifiants sont protégés par ta session (trousseau du système). Pour protéger aussi tes données, active le chiffrement du disque : BitLocker, FileVault ou LUKS.

**Ma banque a changé son site et la synchronisation ne marche plus.**
Le module de connexion de ta banque se met à jour tout seul quand il est corrigé. En attendant, tu peux importer un relevé CSV ou OFX.

**Comment désinstaller ?**
Lance le désinstallateur inclus dans le paquet. Il retire le logiciel et efface tes identifiants du trousseau. Tes données ne sont supprimées que si tu le confirmes.
