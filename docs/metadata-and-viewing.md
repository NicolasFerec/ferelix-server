# Métadonnées et continuité du visionnage

## Configuration

Chaque bibliothèque définit **une seule langue de métadonnées** (`fr-FR` initialement), un profil standard ou animé, et l'activation éventuelle de l'export NFO. Les préférences audio/sous-titres du lecteur restent indépendantes. Un changement de langue relance l'enrichissement sans enlever les verrous administrateur.

Configurer les fournisseurs dans l'environnement du serveur, puis redémarrer :

```dotenv
FERELIX_TMDB_TOKEN=<API Read Access Token TMDB>
FERELIX_ANIDB_CLIENT=<nom de client enregistré auprès d'AniDB>
FERELIX_ANIDB_CLIENT_VERSION=1
FERELIX_METADATA_DIR=/config/metadata
```

En développement, le répertoire par défaut est `server/metadata`. Dans Docker, `/config/metadata` doit être conservé avec le volume `/config`. Sauvegarder **la base SQLite et ce répertoire**. Les secrets fournisseurs ne sont jamais renvoyés au navigateur. Le tableau de bord indique quels fournisseurs sont configurés et expose les tâches en attente, terminées, en erreur ou à identifier.

TMDB fournit les films, séries, saisons, épisodes et collections explicites. AniDB complète les animés ; AniBridge traduit les numérotations lorsque la correspondance est univoque. Une correspondance ambiguë ne déclenche pas d'association automatique. L'éditeur permet de choisir une identité fournisseur ou d'associer un fichier d'épisode non identifié à un épisode existant du catalogue.

Les IDs IMDb explicites dans les noms/NFO sont résolus par identifiant via TMDB. Une absence de correspondance ou une contradiction exige une identification manuelle, sans repli silencieux vers un titre ressemblant.

Les NFO externes sont lus à côté des médias (`movie.nfo`, nom du fichier `.nfo`, `tvshow.nfo`, `season.nfo`). L'export est désactivé par défaut ; l'activer autorise les écritures de NFO à côté des fichiers. Les exports Ferelix inchangés sont reconnus par leur empreinte pour ne pas remplacer ensuite des métadonnées fournisseur plus récentes par leurs propres anciennes valeurs. Une modification extérieure du NFO le rend à nouveau prioritaire. Les images sont validées puis écrites atomiquement en local.

## Modèle et invariants

- `MediaItem` représente une œuvre : film, série, saison, épisode ou collection. Les textes structurés, identifiants, provenance, verrous, révision et empreinte sont persistants.
- `MediaItemFile` associe les œuvres à leurs fichiers physiques. Les identifiants et routes de lecture historiques restent inchangés.
- `UserItemState` porte le statut vu par utilisateur et par œuvre. `MediaView` garde une position physique par utilisateur et fichier, jamais convertie entre éditions.
- `first_available_at` conserve la première disponibilité de l'œuvre. Une seconde édition, un rescan ou une correction de synopsis ne modifie pas cette date.
- La suppression d'un fichier n'efface pas l'œuvre ni son historique utilisateur. Une bibliothèque imbriquée supprimée n'empêche pas l'accès via une bibliothèque parente encore active.

Les fichiers existants sont rattachés progressivement par le worker, par lots de 100, toutes les 15 secondes. Le choix du propriétaire utilise la bibliothèque la plus précise. Un nom explicite avec un ID fournisseur prime sur le titre ; des IDs contradictoires ne sont pas fusionnés. Les noms ou plages d'épisodes ambigus créent un élément à identifier, sans bloquer les lots suivants. Les dates originales des fichiers servent à initialiser la disponibilité ; l'import ne transforme pas tout le catalogue historique en nouveauté.

Le fournisseur importe le détail de **chaque saison**, y compris les épisodes sans fichier. La fiche distingue disponible, manquant, à venir et informations incomplètes. Un échec de récupération est visible ; il bloque l'enchaînement lorsque l'ordre complet ne peut pas être établi. Les spéciaux restent séparés de la continuité principale.

Les cartes utilisent une projection légère, sans synopsis ni distributions complètes. L'empreinte SHA-256 porte sur les champs éditoriaux effectifs et la langue ; l'historique utilisateur et les positions n'y participent pas. Aucun LLM ni index vectoriel n'est créé.

## Enrichissement et édition

Les fournisseurs produisent des propositions, puis un service de fusion applique celles-ci sous contrôle de révision et de génération. Le téléchargement se fait **hors transaction SQL**. Une réponse reçue après une modification administrateur ne peut pas écraser cette modification.

Modifier un champ verrouille ce champ, y compris une valeur vide. Les illustrations ont leurs propres verrous. Le verrou global d'une série/collection protège ses champs et images ; l'inventaire des enfants peut toujours s'enrichir. Le verrou explicite `order` suspend les changements structurels.

Les tâches sont persistantes, dédupliquées par œuvre/génération, avec bail et reprise après erreur. Les recherches/détails TMDB sont mis en cache un jour ; les réponses AniDB et mappings sont également persistants. AniDB est espacé et ses refus déclenchent un délai persistant. Les exports admin utilisent des tâches sans appels fournisseurs. Le worker limite chaque récupération et prépare les illustrations avant la transaction de fusion. Une illustration inaccessible conserve les textes reçus, indique un résultat partiel et sera réessayée.

Les racines sont rafraîchies périodiquement pour découvrir de nouvelles saisons ou de nouveaux films d'une collection. Le service fonctionne avec **un seul worker API**, comme le scanner et le transcodeur existants.

## Visionnage

Les réglages administrateur sont : seuil vu de **90 %** et conservation dans « À suivre » de **90 jours**. `0` désactive cette expiration. Le calcul du seuil est centralisé côté serveur ; une durée inconnue ne permet pas de marquer automatiquement vu. L'ancienne exception « dernière minute » est supprimée. Modifier le seuil agit sur les prochains événements, sans retirer les coches existantes ni recalculer la reprise à la lecture du catalogue.

Les actions « vu/non vu » sont disponibles dans les menus des cartes et les fiches. Pour une saison/série, une prévisualisation indique le nombre d'épisodes concernés ; un jeton de révision protège la confirmation contre une modification simultanée du catalogue ou des états. Seuls les épisodes actuellement connus, hors épisodes explicitement futurs, sont concernés.

« Vu » retire la reprise sans fabriquer de position ni incrémenter le compteur de lectures. « Non vu » remet les reprises de l'œuvre à zéro. Une relecture peut figurer dans « Reprendre » en gardant sa coche. Chaque nouvelle session capture une nouvelle révision ; les heartbeats et fermetures d'anciennes sessions peuvent poursuivre leur suivi technique, mais ne peuvent plus réécrire l'intention utilisateur récente.

## Reprendre, À suivre et lecteur

« Reprendre » contient les positions réellement commencées et non terminées, sur le fichier effectivement utilisé. Ces positions n'expirent pas. « À suivre » propose le premier épisode principal non vu d'une série entamée, ou le premier film non vu d'une collection explicite, par date de sortie. Un ensemble avec une reprise active n'a pas de proposition supplémentaire.

Le service choisit **d'abord l'élément logique requis**, puis vérifie sa disponibilité. Avec E1 présent, E2 absent, E3 présent, E2 bloque la continuation : sa proposition est masquée sur l'accueil et E3 n'est jamais substitué. Des trous numériques, dates de collection ambiguës ou inventaires incomplets donnent `unknown_order`.

L'expiration utilise la dernière activité significative ou la première disponibilité du prochain élément requis. Un heartbeat en pause ne réactive rien. Une série terminée depuis un an réapparaît quand son prochain épisode devient disponible ; un épisode plus lointain ne permet pas de contourner le précédent.

Seul l'événement de **fin réelle** du média ouvre un compte à rebours de 10 secondes. Il peut être annulé, déclenché immédiatement ou désactivé dans les préférences utilisateur. Le serveur revérifie l'ordre et la présence du fichier avant de créer la session suivante ; la précédente est fermée. Atteindre 90 % ne coupe jamais la lecture.

Les fichiers multi-épisodes sans bornes fiables restent signalés et nécessitent un marquage manuel. L'enchaînement depuis un fichier partagé est volontairement bloqué, même si des bornes sont connues : le lecteur actuel signale la fin du fichier physique, pas la fin de chaque segment. Les positions d'un segment connu restent des secondes physiques.

## API

| Fonction | Route |
|---|---|
| Catalogue, recherche, enfants d'une saison | `GET /api/v1/items` |
| Fiche et correspondance fichier | `GET /api/v1/items/{id}`, `GET /api/v1/items/for-file/{file_id}` |
| Reprise / suites | `GET /api/v1/items/resume`, `GET /api/v1/items/next-up` |
| Vu/non vu | `PUT /api/v1/items/{id}/watch-state` avec `expected_revision` |
| Prévisualisation / confirmation groupée | `POST /api/v1/items/{id}/watch-state/bulk` |
| Continuation | `GET /api/v1/items/{id}/continuation?mode=continue\|next` |
| Éditeur, identification, refresh, images | `/api/v1/dashboard/metadata/...` |
| Association manuelle d'un épisode | `POST /api/v1/dashboard/metadata/items/{id}/associate` |

Le résultat de continuation expose `ready`, `missing`, `upcoming`, `unknown_order` ou `complete`. L'association manuelle exige les révisions source/cible, conserve les positions par fichier, reprend l'intention utilisateur la plus récente et invalide les anciennes sessions ; elle refuse les fichiers partagés ambigus et les champs source verrouillés.

La migration `metadata_catalogue` conserve les anciennes positions et initialise les reprises actives. Les associations certaines récupèrent les statuts vus ; aucun lien n'est inventé pour les fichiers historiques disparus. Le downgrade supprime les nouvelles tables/colonnes : sauvegarder avant de revenir en arrière.

Voir [les mesures et scénarios de validation](reviews/2026-11-07/metadata-viewing.md).
