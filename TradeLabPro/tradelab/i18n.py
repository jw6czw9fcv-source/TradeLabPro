"""English or French on screen.

The program is written in English; with French chosen (Settings, or View →
Français), the text on screen is swapped for its French in FR, once the
window is built - labels, buttons, group titles, table headers, hints,
tooltips, menus and the tab row. Text the code sets later goes through tr().

Only what is in FR changes; anything else stays English. A drop-down list is
translated only when it is marked translatable (`mark(combo)`): some are read
back by their text, and those must keep the English the code compares with.
The tab row shows French but answers tabText() in English, for the same
reason. The choice applies at the next start.
"""
from __future__ import annotations

LANG_KEY = "UI/language"
LANGUAGES = (("en", "English"), ("fr", "Français"))
_PROP = "i18n"


def language(settings=None) -> str:
    from tradelab.settings import app_settings
    s = settings or app_settings()
    value = str(s.value(LANG_KEY, "en") or "en")
    return value if value in dict(LANGUAGES) else "en"


_current = None


def current() -> str:
    global _current
    if _current is None:
        try:
            _current = language()
        except Exception:
            _current = "en"
    return _current


def set_current(lang: str) -> None:
    """For the session (and tests); the setting is what the next start reads."""
    global _current
    _current = lang


def tr(text: str) -> str:
    return FR.get(text, text) if current() == "fr" else text


def mark(*combos):
    """Combo boxes read by position, whose items may be translated."""
    for c in combos:
        c.setProperty(_PROP, True)


def translate_tree(root) -> int:
    """Swap the English on screen under `root` for French. Returns how many
    texts changed."""
    from PySide6.QtWidgets import (QAbstractButton, QComboBox, QGroupBox, QLabel, QLineEdit,
                                   QMainWindow, QTableWidget, QWidget)
    if current() != "fr":
        return 0
    n = 0

    def swap(text):
        nonlocal n
        key = (text or "").strip()
        if key in FR:
            n += 1
            return text.replace(key, FR[key])
        return None

    widgets = [root] + root.findChildren(QWidget)
    for w in widgets:
        if isinstance(w, QLabel):
            new = swap(w.text())
            if new is not None:
                w.setText(new)
        elif isinstance(w, QAbstractButton):
            new = swap(w.text())
            if new is not None:
                w.setText(new)
        elif isinstance(w, QGroupBox):
            new = swap(w.title())
            if new is not None:
                w.setTitle(new)
        if isinstance(w, QLineEdit):
            new = swap(w.placeholderText())
            if new is not None:
                w.setPlaceholderText(new)
        if isinstance(w, QTableWidget):
            for c in range(w.columnCount()):
                item = w.horizontalHeaderItem(c)
                new = swap(item.text()) if item else None
                if new is not None:
                    item.setText(new)
        if isinstance(w, QComboBox) and w.property(_PROP):
            for i in range(w.count()):
                new = swap(w.itemText(i))
                if new is not None:
                    w.setItemText(i, new)
        tip = w.toolTip() if hasattr(w, "toolTip") else ""
        new = swap(tip)
        if new is not None:
            w.setToolTip(new)
    if isinstance(root, QMainWindow):
        # Through the menus themselves: QAction.menu() hands a menu to Python,
        # which then deletes it.
        from PySide6.QtWidgets import QMenu
        for menu in root.menuBar().findChildren(QMenu):
            new = swap(menu.title())
            if new is not None:
                menu.setTitle(new)
            for a in menu.actions():
                new = swap(a.text())
                if new is not None:
                    a.setText(new)
    return n


# The French. Keys are the English exactly as the program writes it.
FR = {
    # Tabs and menus
    "Guide": "Guide", "Home": "Accueil", "Market": "Marché", "Heatmap": "Carte thermique",
    "News": "Nouvelles", "Scanner": "Scanneur", "ETF Screener": "Filtre de FNB",
    "Watchlists": "Listes de suivi", "Alerts": "Alertes", "AI Assist": "Assistant IA",
    "Risk": "Risque", "Paper Trading": "Négociation simulée", "Portfolio": "Portefeuille",
    "Analytics": "Analyse", "Dividends": "Dividendes", "Retirement": "Retraite",
    "Retirement Sim": "Simulation retraite", "Plan": "Plan", "Journal": "Journal",
    "Coach": "Coach", "Backtest": "Test historique", "Strategies": "Stratégies",
    "Replay": "Relecture", "Seasonality": "Saisonnalité", "Plugins": "Modules",
    "Notes": "Notes", "Links": "Liens", "Settings": "Paramètres", "Help": "Aide",
    "&View": "&Affichage", "&Help": "&Aide", "Advanced mode - all tabs": "Mode avancé - tous les onglets",
    "User Manual": "Manuel d'utilisation", "Revision history": "Historique des versions",
    "Version": "Version", "Language": "Langue",
    "Simple mode ▸ show all tabs": "Mode simple ▸ afficher tous les onglets",
    "Advanced mode ▸ show fewer tabs": "Mode avancé ▸ afficher moins d'onglets",
    "Simple shows the tabs needed to invest calmly; Advanced shows every tab. Nothing is lost either way.":
        "Le mode simple montre les onglets utiles pour investir sereinement; le mode avancé les "
        "montre tous. Rien n'est perdu dans un cas comme dans l'autre.",
    "Not financial advice.": "Ceci n'est pas un conseil financier.",

    # Common
    "Refresh": "Actualiser", "Save": "Enregistrer", "Check": "Vérifier", "Yes": "Oui", "No": "Non",
    "Not sure": "Pas certain", "←  Back": "←  Retour", "Symbol": "Symbole", "Name": "Nom",
    "Account": "Compte", "Value": "Valeur", "Date": "Date", "Kind": "Type", "Amount": "Montant",
    "Note": "Note", "Remove selected": "Retirer la sélection", "Export": "Exporter",
    "Currency": "Devise", "Chart": "Graphique", "Price": "Prix", "Cost": "Coût",
    "for": "pour", "into": "dans", "as of": "au", "Shares": "Parts", "Entry": "Entrée",
    "Level": "Niveau", "Period": "Période", "Show": "Afficher", "Order by": "Trier par",
    "Also check": "Vérifier aussi", "Loading…": "Chargement…",

    # Guide - step 1
    "New to investing? This guide takes you through it one step at a time: a few questions about "
    "you, then the level of risk that fits your answers - with what it may return and what it "
    "really did in bad years. You choose; TradeLab never picks for you. Not financial advice.":
        "Nouveau en placement? Ce guide vous accompagne une étape à la fois : quelques questions "
        "sur vous, puis le niveau de risque qui correspond à vos réponses - avec ce qu'il peut "
        "rapporter et ce qu'il a vraiment fait dans les mauvaises années. Vous choisissez; "
        "TradeLab ne choisit jamais à votre place. Ceci n'est pas un conseil financier.",
    "Step 1 of 4 - About you": "Étape 1 de 4 - Vous",
    "When will you need this money?": "Quand aurez-vous besoin de cet argent?",
    "Less than 2 years": "Moins de 2 ans", "2 to 3 years": "2 à 3 ans", "4 to 5 years": "4 à 5 ans",
    "6 to 9 years": "6 à 9 ans", "10 to 14 years": "10 à 14 ans", "15 years or more": "15 ans ou plus",
    "How big a drop could you live through without selling?":
        "Quelle baisse pourriez-vous traverser sans vendre?",
    "No drop at all": "Aucune baisse", "About 5%": "Environ 5 %", "About 10%": "Environ 10 %",
    "About 20%": "Environ 20 %", "About 30%": "Environ 30 %", "More than 30%": "Plus de 30 %",
    "A 20% drop turns $10,000 into $8,000 for a while - months, sometimes years. Selling then "
    "makes the loss permanent.":
        "Une baisse de 20 % fait passer 10 000 $ à 8 000 $ pour un temps - des mois, parfois des "
        "années. Vendre à ce moment rend la perte permanente.",
    "Which accounts do you have?": "Quels comptes avez-vous?",
    "CELI and REER": "CELI et REER", "CELI only": "CELI seulement", "REER only": "REER seulement",
    "Neither yet": "Aucun pour l'instant",
    "Amount to invest now": "Montant à placer maintenant",
    "Amount you can add each month": "Montant que vous pouvez ajouter chaque mois",
    "Do you have a few months of expenses set aside?":
        "Avez-vous quelques mois de dépenses de côté?",
    "Do you owe on a credit card or loan at a high rate?":
        "Avez-vous une dette de carte de crédit ou un prêt à taux élevé?",
    "Next: your level  →": "Suivant : votre niveau  →",

    # Guide - step 2
    "Step 2 of 4 - Your level": "Étape 2 de 4 - Votre niveau",
    "What it did since 2003": "Ce qu'il a fait depuis 2003",
    "What it did the last 10 years": "Ce qu'il a fait ces 10 dernières années",
    "What it did the last 3 years": "Ce qu'il a fait ces 3 dernières années",
    "What it did the last year": "Ce qu'il a fait la dernière année",
    "Planners' guidelines (cautious)": "Normes des planificateurs (prudentes)",
    "Stocks / bonds / cash": "Actions / obligations / liquidités",
    "Did a year": "A fait par an", "Guidelines, a year*": "Normes, par an*",
    "Your money in … years": "Votre argent dans … ans",
    "Worst fall (when)": "Pire baisse (quand)", "Worst 12 months": "Pires 12 mois",
    "Worst 5 years, a year": "Pires 5 ans, par an",
    "Did a year, {window}": "A fait par an, {window}",
    "Your money in {years} years": "Votre argent dans {years} ans",
    "Worst fall, {window} (when)": "Pire baisse, {window} (quand)",
    "since 2003": "depuis 2003", "the last 10 years": "ces 10 dernières années",
    "the last 3 years": "ces 3 dernières années", "the last year": "la dernière année",
    "Make it your plan": "En faire votre plan", "For portfolio": "Pour le portefeuille",
    "Use this level": "Utiliser ce niveau", "Next: your funds  →": "Suivant : vos fonds  →",
    "The returns, the falls and your money below all follow it.":
        "Les rendements, les baisses et votre argent ci-dessous suivent ce choix.",
    "Capital first": "Capital d'abord", "Cautious": "Prudent", "Conservative": "Conservateur",
    "Balanced": "Équilibré", "Growth": "Croissance", "All stocks": "Toutes actions",
    "What each level really did, in CAD, over the period you pick: index funds in a typical "
    "global mix (Canada 30%, US 45%, international 20%, emerging 5% - XIU, SPY, EFA, EEM, the "
    "US-listed ones at each month's exchange rate, unhedged as an all-in-one ETF holds them), "
    "bonds XBB, cash at a steady 2.4%, rebalanced monthly. They stand in for stocks and bonds and "
    "are not picks. * The FP Canada / IQPF Projection Assumption Guidelines 2026 are what "
    "financial planners are told to assume - deliberately cautious, less a 0.25% fee. The last 10 "
    "years were unusually strong for US stocks, and a short period can miss a crash entirely: the "
    "level marked ★ is always judged on the worst fall since 2003, 2008 included, because one "
    "like it can come again. The past is no promise. Not financial advice.":
        "Ce que chaque niveau a vraiment fait, en $ CA, sur la période choisie : des fonds "
        "indiciels dans un mélange mondial typique (Canada 30 %, États-Unis 45 %, international "
        "20 %, émergents 5 % - XIU, SPY, EFA, EEM, ceux cotés aux États-Unis au taux de change de "
        "chaque mois, non couverts comme dans un FNB tout-en-un), obligations XBB, liquidités à "
        "2,4 % stable, rééquilibré chaque mois. Ils représentent les actions et les obligations; "
        "ce ne sont pas des choix. * Les Normes d'hypothèses de projection 2026 de FP Canada et "
        "de l'IQPF sont ce que les planificateurs financiers doivent supposer - volontairement "
        "prudentes, moins des frais de 0,25 %. Les 10 dernières années ont été exceptionnelles "
        "pour les actions américaines, et une courte période peut manquer un krach : le niveau "
        "marqué ★ est toujours jugé sur la pire baisse depuis 2003, 2008 compris, car une "
        "pareille peut revenir. Le passé n'est pas une promesse. Ceci n'est pas un conseil "
        "financier.",

    # Guide - step 3
    "Step 3 of 4 - Your funds": "Étape 3 de 4 - Vos fonds",
    "Lowest fees": "Frais les plus bas", "Smallest worst fall": "Plus petite pire baisse",
    "Lowest risk": "Risque le plus bas", "Best 10-year return": "Meilleur rendement sur 10 ans",
    "Best 5-year return": "Meilleur rendement sur 5 ans", "Least overlap": "Moins de chevauchement",
    "other symbols, e.g. VDY.TO": "autres symboles, ex. VDY.TO",
    "Fees/yr": "Frais/an", "Risk (CSA)": "Risque (ACVM)", "1 yr": "1 an",
    "5 yr, a year": "5 ans, par an", "10 yr, a year": "10 ans, par an",
    "Add selected to my funds  ↓": "Ajouter la sélection à mes fonds  ↓",
    "Remove from my funds": "Retirer de mes fonds",
    "My funds - what step 4 buys": "Mes fonds - ce que l'étape 4 achète",
    "One fund for {name}": "Un seul fonds pour {name}",
    "Building block: {name}": "Bloc : {name}",
    "Cash and savings": "Liquidités et épargne", "Short-term bonds": "Obligations à court terme",
    "Bonds, all terms": "Obligations, toutes échéances", "Canadian stocks": "Actions canadiennes",
    "Canadian dividend stocks": "Actions canadiennes à dividendes",
    "U.S. stocks (S&P 500)": "Actions américaines (S&P 500)",
    "International stocks": "Actions internationales",
    "Global stocks, outside Canada": "Actions mondiales, hors Canada",
    "Next: your purchases  →": "Suivant : vos achats  →",
    "One fund for your level holds stocks and bonds in that mix and rebalances itself - the least "
    "work, and the fewest ways to go wrong. Building blocks are one fund per part (cash, bonds, "
    "Canadian, US, international stocks): more control, and you rebalance them yourself - the Plan "
    "tab shows when. The candidates are broad index ETFs from three providers, side by side; "
    "returns include dividends, in CAD. Account: \"REER\" when a US-listed fund's dividends would "
    "lose 15% to US tax in a CELI. TradeLab orders them by what you choose and never picks. Not "
    "financial advice.":
        "Un seul fonds pour votre niveau détient actions et obligations dans ce mélange et se "
        "rééquilibre lui-même - le moins de travail et le moins de façons de se tromper. Les "
        "blocs sont un fonds par partie (liquidités, obligations, actions canadiennes, "
        "américaines, internationales) : plus de contrôle, et vous les rééquilibrez vous-même - "
        "l'onglet Plan dit quand. Les candidats sont des FNB indiciels larges de trois "
        "fournisseurs, côte à côte; les rendements incluent les dividendes, en $ CA. Compte : "
        "« REER » quand les dividendes d'un fonds coté aux États-Unis perdraient 15 % en impôt "
        "américain dans un CELI. TradeLab les trie selon votre choix et ne choisit jamais. Ceci "
        "n'est pas un conseil financier.",

    # Guide - step 4
    "Step 4 of 4 - Your purchases": "Étape 4 de 4 - Vos achats",
    "Invest now": "Placer maintenant", "Use its recorded cash": "Utiliser ses liquidités inscrites",
    "then each month": "puis chaque mois", "Fund": "Fonds", "For": "Pour", "Share %": "Part %",
    "Held now": "Détenu", "Buy now": "Acheter maintenant", "Then each month": "Puis chaque mois",
    "Copy the list": "Copier la liste", "Remind me each month on day": "Me le rappeler chaque mois le",
    "A Windows notification with this month's purchase, when TradeLab is open on or after that "
    "day - once a month.":
        "Une notification Windows avec l'achat du mois, quand TradeLab est ouvert ce jour-là ou "
        "après - une fois par mois.",
    "Whole shares only, at the last closing price - the price will have moved a little when you "
    "buy. Each fund below its share gets the money first, so nothing has to be sold; what is left "
    "stays as cash. Place the orders yourself at your broker (a limit order near the price shown "
    "keeps a surprise out); TradeLab never trades. The monthly line assumes today's purchase is "
    "made. A fund listed in the US is priced in CAD at today's exchange rate. Not financial advice.":
        "Parts entières seulement, au dernier cours de clôture - le prix aura un peu bougé quand "
        "vous achèterez. Chaque fonds sous sa part reçoit l'argent en premier, donc rien n'est "
        "vendu; le reste demeure en liquidités. Passez les ordres vous-même chez votre courtier "
        "(un ordre à cours limité près du prix affiché évite les surprises); TradeLab ne négocie "
        "jamais. La ligne mensuelle suppose que l'achat d'aujourd'hui est fait. Un fonds coté aux "
        "États-Unis est évalué en $ CA au taux du jour. Ceci n'est pas un conseil financier.",

    # Home
    "Your portfolio at a glance": "Votre portefeuille en un coup d'œil",
    "This year (estimated)": "Cette année (estimé)", "Recorded history": "Historique enregistré",
    "Estimated: today's share counts valued back through the year. Recorded: what the account was "
    "really worth each day TradeLab priced it - deposits, trades and dividends included as they "
    "happened.":
        "Estimé : les quantités d'aujourd'hui évaluées sur l'année. Enregistré : ce que le compte "
        "valait vraiment chaque jour où TradeLab l'a évalué - dépôts, transactions et dividendes "
        "inclus quand ils sont arrivés.",
    "Native (mixed)": "Native (mixte)",
    "Loading your portfolio…": "Chargement de votre portefeuille…",
    "Book value": "Valeur du portefeuille", "Today": "Aujourd'hui",
    "Unrealized P&L": "Gain/perte non réalisé", "Annual income": "Revenu annuel",
    "Net worth": "Valeur nette", "This year": "Cette année", "Needs attention": "À surveiller",
    "Today's movers": "Plus fortes variations du jour", "Change %": "Variation %",
    "Click a holding to chart it.": "Cliquez un titre pour en voir le graphique.",
    "Figures come from the Analytics and Dividends tabs — open those for the full breakdown. "
    "Analysis only — this never places or tracks live orders.":
        "Les chiffres viennent des onglets Analyse et Dividendes — ouvrez-les pour le détail. "
        "Analyse seulement — aucun ordre réel n'est passé ni suivi.",
    "Your plan:": "Votre plan :", "Open the Plan tab": "Ouvrir l'onglet Plan",
    "Your plan is on track.": "Votre plan est sur la bonne voie.",

    # Plan
    "Your plan, checked. You set the mix each portfolio should hold, which portfolio is for "
    "trading and how big it may get; TradeLab shows how far each one is from it and what moving "
    "back would take in dollars. It never chooses a mix or a security - the moves shown are what "
    "it would take, not what to do.":
        "Votre plan, vérifié. Vous fixez le mélange de chaque portefeuille, lequel sert à la "
        "négociation et jusqu'où il peut aller; TradeLab montre l'écart de chacun et ce qu'il "
        "faudrait en dollars pour y revenir. Il ne choisit jamais un mélange ni un titre - les "
        "mouvements montrés sont ce qu'il faudrait, pas ce qu'il faut faire.",
    "Checklist": "Liste de vérification",
    "Target mix per portfolio (your choice, %)": "Mélange cible par portefeuille (votre choix, %)",
    "Stocks %": "Actions %", "Bonds %": "Obligations %", "Cash %": "Liquidités %",
    "Save targets": "Enregistrer les cibles", "Trading portfolio": "Portefeuille de négociation",
    "may be at most": "peut être au plus",
    "A trading portfolio: at most this share of everything. Holdings set to \"trading\" inside a "
    "portfolio: at most this share of that portfolio.":
        "Un portefeuille de négociation : au plus cette part du total. Les titres marqués "
        "« trading » dans un portefeuille : au plus cette part de ce portefeuille.",
    "of everything - or of each portfolio, for holdings set to \"trading\"":
        "du total - ou de chaque portefeuille, pour les titres marqués « trading »",
    "No review recorded yet.": "Aucune révision inscrite.",
    "Mark reviewed today": "Marquer révisé aujourd'hui",
    "Contribution room - CELI and REER": "Droits de cotisation - CELI et REER",
    "Type the room CRA shows (My Account; for the REER, the deduction limit on your latest Notice "
    "of Assessment) and its date, then record each deposit and withdrawal you make - in every CELI "
    "or REER you have, group plans included. A CELI withdrawal comes back as room on January 1; "
    "the 2026 CELI limit of $7,000 is added on its January 1. An excess is taxed 1% a month (for "
    "the REER, beyond a $2,000 allowance) - canada.ca. The deposits also let the return above "
    "leave your own money out.":
        "Inscrivez les droits que montre l'ARC (Mon dossier; pour le REER, le plafond de "
        "déduction de votre dernier avis de cotisation) et leur date, puis chaque dépôt et "
        "retrait que vous faites - dans tous vos CELI et REER, régimes collectifs compris. Un "
        "retrait du CELI redevient des droits le 1er janvier; le plafond CELI 2026 de 7 000 $ "
        "s'ajoute le 1er janvier. Un excédent est imposé à 1 % par mois (pour le REER, au-delà "
        "d'une marge de 2 000 $) - canada.ca. Les dépôts permettent aussi au rendement ci-dessus "
        "d'exclure votre propre argent.",
    "CELI room": "Droits CELI", "REER room": "Droits REER", "Deposit": "Dépôt",
    "Withdrawal": "Retrait", "note (optional)": "note (facultatif)", "Record": "Inscrire",
    "No room typed yet.": "Aucun droit inscrit.",
    "What each portfolio holds, by class (set a class by hand if the automatic one is wrong, or "
    "\"trading\" for a swing trade - it then stays out of the mix and counts against the trading "
    "cap)":
        "Ce que détient chaque portefeuille, par catégorie (choisissez une catégorie si "
        "l'automatique est fausse, ou « trading » pour une négociation à court terme - elle sort "
        "alors du mélange et compte dans le plafond de négociation)",
    "Value (CAD)": "Valeur ($ CA)", "Class": "Catégorie", "Against the target": "Par rapport à la cible",
    "Held (CAD)": "Détenu ($ CA)", "Held %": "Détenu %", "Target %": "Cible %",
    "To get back": "Pour y revenir",
    "Candidate check - the facts before you buy": "Vérification d'un candidat - les faits avant d'acheter",
    "Symbol, e.g. XBB.TO": "Symbole, ex. XBB.TO", "(no portfolio)": "(aucun portefeuille)",
    "Fees, risk band, worst fall, returns, overlap with what you own, the part of your plan it "
    "adds to, and which account suits it - facts with their basis, not a verdict. ⚠ marks "
    "something worth a second look.":
        "Frais, niveau de risque, pire baisse, rendements, chevauchement avec ce que vous "
        "détenez, la partie de votre plan qu'il renforce et le compte qui lui convient - des "
        "faits avec leur source, pas un verdict. ⚠ signale ce qui mérite un deuxième regard.",
    "Click Refresh to price your portfolios.": "Cliquez Actualiser pour évaluer vos portefeuilles.",

    # Portfolio
    "Portfolio:": "Portefeuille :", "Add Position puts the position here.":
        "Ajouter une position la place ici.",
    "Add…": "Ajouter…", "Rename…": "Renommer…", "Remove…": "Retirer…",
    "One portfolio per account. Renaming carries its positions, cash, target mix and startup sync "
    "along.":
        "Un portefeuille par compte. Renommer emporte ses positions, ses liquidités, son mélange "
        "cible et sa synchronisation au démarrage.",
    "Add Position": "Ajouter une position", "Delete selected": "Supprimer la sélection",
    "Export Portfolio": "Exporter le portefeuille", "Import from IBKR:": "Importer d'IBKR :",
    "Positions file (CSV/XML)…": "Fichier de positions (CSV/XML)…",
    "Fetch positions (Flex)": "Récupérer les positions (Flex)",
    "The portfolio this import replaces - use one per IBKR account.":
        "Le portefeuille que cette importation remplace - un par compte IBKR.",
    "Sync this portfolio when TradeLab starts": "Synchroniser ce portefeuille au démarrage",
    "Each time TradeLab starts, fetch this portfolio's Flex report and replace it with what it "
    "holds - no question asked. Tick it for each IBKR account (a REER, a CELI), each with its own "
    "query id.":
        "À chaque démarrage, TradeLab récupère le rapport Flex de ce portefeuille et le remplace "
        "par son contenu - sans rien demander. Cochez-le pour chaque compte IBKR (un REER, un "
        "CELI), chacun avec son propre numéro de requête.",
    "query id (blank: Journal's)": "no de requête (vide : celui du Journal)",
    "The Flex query for this account. Blank uses the query id saved in the Journal tab.":
        "La requête Flex de ce compte. Vide : celle enregistrée dans l'onglet Journal.",
    "Imports your open positions - and the cash, when the report has its Cash Report section - "
    "into the portfolio named beside the buttons; each import replaces what that portfolio held "
    "(read-only). The Flex pull reuses the token and query id you saved in the Journal tab — use a "
    "query that includes the Open Positions section.":
        "Importe vos positions ouvertes - et les liquidités, quand le rapport contient sa section "
        "Cash Report - dans le portefeuille nommé à côté des boutons; chaque importation remplace "
        "ce qu'il contenait (lecture seule). La récupération Flex utilise le jeton et le numéro "
        "de requête enregistrés dans l'onglet Journal — utilisez une requête qui inclut la "
        "section Open Positions.",
    "Click a position to chart its symbol.": "Cliquez une position pour voir son graphique.",
    "Cash:": "Liquidités :", "The portfolio this cash belongs to.":
        "Le portefeuille auquel appartiennent ces liquidités.",
    "A negative amount is a margin loan: it is owed, so it lowers the account's value.":
        "Un montant négatif est un prêt sur marge : il est dû, donc il réduit la valeur du compte.",
    "Set cash": "Inscrire les liquidités", "Remove selected cash": "Retirer les liquidités sélectionnées",
    "The cash each account holds, per currency. Home and Analytics add it to your positions, so "
    "their total matches the value your broker shows. Setting it again replaces the amount.":
        "Les liquidités de chaque compte, par devise. Accueil et Analyse les ajoutent à vos "
        "positions, pour que le total corresponde à ce que montre votre courtier. Les inscrire de "
        "nouveau remplace le montant.",
    "Set on": "Inscrit le",

    # --- Phase 2: messages built on the fly --------------------------------------------
    # Classes and small words
    "stocks": "actions", "bonds": "obligations", "cash": "liquidités", "other": "autre",
    "buy": "acheter", "sell": "vendre", "of": "de",
    "no drop at all": "aucune baisse", "a drop of about 5%": "une baisse d'environ 5 %",
    "a drop of about 10%": "une baisse d'environ 10 %", "a drop of about 20%": "une baisse d'environ 20 %",
    "a drop of about 30%": "une baisse d'environ 30 %", "a drop of more than 30%": "une baisse de plus de 30 %",
    # Guide
    "Your answers point to {level}.": "Vos réponses mènent à {level}.",
    "Because ": "Parce que ", " - and ": " - et ",
    "you need the money in {horizon}, and a higher level can take longer than that to recover from a fall":
        "vous aurez besoin de l'argent dans {horizon}, et un niveau plus élevé peut prendre plus de "
        "temps que cela à se remettre d'une baisse",
    "you need the money in {horizon} - time to wait out a fall":
        "vous aurez besoin de l'argent dans {horizon} - le temps d'attendre la fin d'une baisse",
    "you want {phrase}, and {level} is the level that fell least ({fall})":
        "vous voulez {phrase}, et {level} est le niveau qui a le moins baissé ({fall})",
    "you could live with {phrase}, and {level} fell {fall} at worst":
        "vous pourriez vivre avec {phrase}, et {level} a baissé de {fall} au pire",
    "you could live with {phrase}": "vous pourriez vivre avec {phrase}",
    "Only savings accounts and GICs (term deposits) never drop.":
        "Seuls les comptes d'épargne et les CPG (dépôts à terme) ne baissent jamais.",
    "Before you start: ": "Avant de commencer : ",
    "Keep a few months of expenses in a savings account first, so an emergency never forces you "
    "to sell after a drop.":
        "Gardez d'abord quelques mois de dépenses dans un compte d'épargne, pour qu'une urgence ne "
        "vous force jamais à vendre après une baisse.",
    "A credit card or loan at 15-20% costs more than any level here is expected to earn: paying it "
    "off is a sure return.":
        "Une carte de crédit ou un prêt à 15-20 % coûte plus que ce qu'aucun niveau ici devrait "
        "rapporter : le rembourser est un rendement assuré.",
    "A CELI or a REER keeps the growth from being taxed every year. The next step of the guide "
    "places funds by account.":
        "Un CELI ou un REER évite que la croissance soit imposée chaque année. L'étape suivante du "
        "guide place les fonds par compte.",
    "{chosen} is above the level your answers point to ({recommended}).{fall} It is your choice.":
        "{chosen} est au-dessus du niveau auquel mènent vos réponses ({recommended}).{fall} C'est "
        "votre choix.",
    " It fell {fall} at worst.": " Il a baissé de {fall} au pire.",
    "{name}: {st} stocks, {bo} bonds, {ca} cash.":
        "{name} : {st} actions, {bo} obligations, {ca} liquidités.",
    " In its worst stretch since {since}, $10,000 became {value}.":
        " Dans sa pire période depuis {since}, 10 000 $ sont devenus {value}.",
    "{window} is too short to judge a level: it can miss a crash entirely, and a strong stretch "
    "does not repeat on demand.":
        "{window}, c'est trop court pour juger un niveau : on peut y manquer un krach, et une "
        "bonne période ne se répète pas sur commande.",
    "Saved: {name}.": "Enregistré : {name}.",
    " It is now {portfolio}'s target mix in the Plan tab, which shows what it would take to get "
    "there.":
        " C'est maintenant le mélange cible de {portfolio} dans l'onglet Plan, qui montre ce qu'il "
        "faudrait pour y arriver.",
    " Pick a portfolio to make it that portfolio's target mix in the Plan tab.":
        " Choisissez un portefeuille pour en faire son mélange cible dans l'onglet Plan.",
    "Your level: {level} (chosen {date}": "Votre niveau : {level} (choisi le {date}",
    ", for {portfolio}": ", pour {portfolio}",
    "). Go through the steps again any time.": "). Refaites les étapes quand vous voulez.",
    "Measuring what each level really did since 2003…":
        "Mesure de ce que chaque niveau a vraiment fait depuis 2003…",
    "Measured on real prices since {since}.": "Mesuré sur les prix réels depuis {since}.",
    "{name}: {split}. Either one fund that does it all, or one fund per part - compare them below.":
        "{name} : {split}. Soit un seul fonds qui fait tout, soit un fonds par partie - "
        "comparez-les ci-dessous.",
    "Checking {symbols}…": "Vérification de {symbols}…",
    "Facts from real prices, dividends included. Not advice.":
        "Faits tirés des prix réels, dividendes compris. Pas un conseil.",
    "For {portfolio}:": "Pour {portfolio} :", "For your account:": "Pour votre compte :",
    "Getting the last prices…": "Récupération des derniers prix…",
    "Prices are the last close.": "Les prix sont ceux de la dernière clôture.",
    "The shares add up to {total}: the other {rest} stays as cash.":
        "Les parts totalisent {total} : les {rest} restants demeurent en liquidités.",
    "The shares add up to {total} - more than the money.":
        "Les parts totalisent {total} - plus que l'argent disponible.",
    "No fund picked yet for {parts} - add one in step 3, or that part stays as cash.":
        "Aucun fonds choisi pour {parts} - ajoutez-en un à l'étape 3, sinon cette partie demeure "
        "en liquidités.",
    "The portfolio also holds {amount} in other holdings; they are left alone here (the Plan tab "
    "weighs the whole account).":
        "Le portefeuille détient aussi {amount} en autres titres; ils ne sont pas touchés ici "
        "(l'onglet Plan pèse le compte entier).",
    "Now: buy for {spent}, {left} left as cash.":
        "Maintenant : acheter pour {spent}, {left} restent en liquidités.",
    " Each month after: buy for {spent}; {left} carried to the next month.":
        " Chaque mois ensuite : acheter pour {spent}; {left} reportés au mois suivant.",
    "Next purchase: {date}.": "Prochain achat : {date}.",
    "TradeLab - your monthly purchase": "TradeLab - votre achat du mois",
    "Time for this month's purchase: {amount} - {parts}. The Guide's step 4 has the share counts.":
        "C'est le moment de l'achat du mois : {amount} - {parts}. L'étape 4 du Guide donne le "
        "nombre de parts.",
    "Time for this month's purchase - the Guide's step 4 has the share counts.":
        "C'est le moment de l'achat du mois - l'étape 4 du Guide donne le nombre de parts.",
    "TradeLab - the market has fallen": "TradeLab - le marché a baissé",
    "Global stocks are {fall} below their high of {high}. Falls like this are part of investing, "
    "and of your plan.":
        "Les actions mondiales sont {fall} sous leur sommet du {high}. Les baisses comme "
        "celle-ci font partie du placement, et de votre plan.",
    " {level} fell {fall} at worst since 2003 ({when})":
        " {level} a baissé de {fall} au pire depuis 2003 ({when})",
    " and was back to its high by {date}, {months} months later":
        " et était revenu à son sommet en {date}, {months} mois plus tard",
    " Selling after a fall turns it into a loss for good; your plan has not changed.":
        " Vendre après une baisse la transforme en perte définitive; votre plan n'a pas changé.",
    # Plan
    "{name}: swing trades {amount} are {share} of the portfolio, {verdict}.":
        "{name} : les négociations à court terme ({amount}) font {share} du portefeuille, {verdict}.",
    "above its {cap} cap by {room}": "au-dessus de son plafond de {cap} de {room}",
    "inside its {cap} cap ({room} of room)": "sous son plafond de {cap} ({room} de marge)",
    "{name}: empty - its target mix applies once money is in it.":
        "{name} : vide - son mélange cible s'appliquera une fois l'argent déposé.",
    "{name}: no target mix set - type one above.":
        "{name} : aucun mélange cible - inscrivez-en un ci-dessus.",
    "{name}: {amount} of cash beyond your target cash share - by your target mix, putting it to "
    "work without selling anything would mean {parts}. Pick the funds with the candidate check "
    "below.":
        "{name} : {amount} de liquidités au-delà de votre part cible - selon votre mélange cible, "
        "les placer sans rien vendre voudrait dire {parts}. Choisissez les fonds avec la "
        "vérification d'un candidat ci-dessous.",
    "{name}: off its target ({gaps}) - getting back would take: {moves}.":
        "{name} : hors de sa cible ({gaps}) - pour y revenir, il faudrait : {moves}.",
    "{name}: on target (largest gap {gap} points).":
        "{name} : dans la cible (plus grand écart {gap} points).",
    "Trading ({name}) is {share} of everything, above its {cap} cap by {room}.":
        "La négociation ({name}) fait {share} du total, au-dessus de son plafond de {cap} de {room}.",
    "Trading ({name}) is {share} of everything, inside its {cap} cap ({room} of room).":
        "La négociation ({name}) fait {share} du total, sous son plafond de {cap} ({room} de marge).",
    "No trading portfolio chosen and no holding set to \"trading\" - do one or the other to keep "
    "trading capped.":
        "Aucun portefeuille de négociation choisi et aucun titre marqué « trading » - faites l'un "
        "ou l'autre pour plafonner la négociation.",
    "Safe budget not checked yet - Retirement Sim → Safe budget.":
        "Budget sécuritaire pas encore vérifié - Simulation retraite → Budget sécuritaire.",
    "Spending {spending} is above the safe budget of {safe} a year (checked {checked}).":
        "Les dépenses de {spending} dépassent le budget sécuritaire de {safe} par an (vérifié le "
        "{checked}).",
    "Spending {spending} is under the safe budget of {safe} a year (checked {checked}).":
        "Les dépenses de {spending} sont sous le budget sécuritaire de {safe} par an (vérifié le "
        "{checked}).",
    "Review due: go through this list, then Mark reviewed today.":
        "Révision due : parcourez cette liste, puis Marquer révisé aujourd'hui.",
    "Next review around {date} ({days} days).": "Prochaine révision vers le {date} ({days} jours).",
    "Last review {last}; next around {next} (about every quarter).":
        "Dernière révision le {last}; prochaine vers le {next} (environ chaque trimestre).",
    "TradeLab - {n} thing(s) to look at in your plan": "TradeLab - {n} point(s) à voir dans votre plan",
    " (and more in the Plan tab)": " (et d'autres dans l'onglet Plan)",
    " (and {n} more)": " (et {n} autre(s))",
    "Targets saved.": "Cibles enregistrées.",
    "No portfolios yet - add positions in the Portfolio tab.":
        "Aucun portefeuille - ajoutez des positions dans l'onglet Portefeuille.",
    "Pricing your portfolios…": "Évaluation de vos portefeuilles…",
    "Your return: not enough recorded to measure yet.":
        "Votre rendement : pas encore assez de données pour le mesurer.",
    "Your return: TradeLab needs a few days of recorded values first (Home records one each day "
    "it prices your book).":
        "Votre rendement : TradeLab a d'abord besoin de quelques jours de valeurs enregistrées "
        "(Accueil en enregistre une chaque jour où il évalue vos comptes).",
    "Your return: choose a level in the Guide to compare it with.":
        "Votre rendement : choisissez un niveau dans le Guide pour le comparer.",
    "Since {date} ({days} days)": "Depuis le {date} ({days} jours)",
    "{since}: your book did {mine} a year, your deposits left out":
        "{since} : vos comptes ont fait {mine} par an, sans compter vos dépôts",
    "; {level} did {theirs} a year.": "; {level} a fait {theirs} par an.",
    " The past is no promise.": " Le passé n'est pas une promesse.",
    "{since}: your book {mine}, your deposits left out":
        "{since} : vos comptes {mine}, sans compter vos dépôts",
    "; {level} {theirs} over the same days": "; {level} {theirs} sur les mêmes jours",
    ". Too short to judge - compare after a year.": ". Trop court pour juger - comparez après un an.",
    # Contribution room
    "{name}: {left} of room left.": "{name} : {left} de droits restants.",
    " {amount} withdrawn comes back on January 1.": " {amount} retirés reviennent le 1er janvier.",
    "{name} room: a new year began - type the room CRA shows now (My Account) so it stays right.":
        "Droits {name} : une nouvelle année a commencé - inscrivez les droits que montre l'ARC "
        "(Mon dossier) pour qu'ils restent justes.",
    "{name}: {over} over your room - taxed {taxed}. Withdrawing the excess soon limits the tax.":
        "{name} : {over} au-delà de vos droits - imposé à {taxed}. Retirer l'excédent rapidement "
        "limite l'impôt.",
    "1% a month on the highest excess each month": "1 % par mois sur l'excédent le plus élevé du mois",
    "1% a month on what is beyond the $2,000 allowance": "1 % par mois sur ce qui dépasse la marge de 2 000 $",
    "{name}: {over} over your deduction limit, inside the $2,000 allowance - not taxed, but not "
    "deductible this year.":
        "{name} : {over} au-delà de votre plafond de déduction, dans la marge de 2 000 $ - pas "
        "imposé, mais pas déductible cette année.",

    # --- Phase 2: Retirement Sim -----------------------------------------------------------
    "Spending": "Dépenses",
    "Household spending per year, in today's dollars — it grows with inflation from there. The "
    "input that moves the answer more than any other.":
        "Dépenses du ménage par année, en dollars d'aujourd'hui — elles augmentent ensuite avec "
        "l'inflation. La donnée qui change le plus le résultat.",
    "Return": "Rendement",
    "The return as a fund reports it, with inflation still in it. 5 means five percent.":
        "Le rendement tel qu'un fonds le publie, inflation comprise. 5 veut dire cinq pour cent.",
    "Projected explicitly rather than netted out of the return. It grows the indexed benefits "
    "(RRQ, PSV, AOW), the spending, and the tax brackets — which are indexed by law, so leaving "
    "them frozen would invent bracket creep that will not happen.":
        "Projetée explicitement plutôt que retranchée du rendement. Elle fait croître les "
        "prestations indexées (RRQ, PSV, AOW), les dépenses et les paliers d'impôt — indexés par "
        "la loi, donc les figer inventerait une hausse d'impôt qui n'arrivera pas.",
    "How much the return varies year to year. This is what turns one projection into a range - "
    "and what makes the order of the returns matter.":
        "À quel point le rendement varie d'une année à l'autre. C'est ce qui transforme une "
        "projection en fourchette - et ce qui rend l'ordre des rendements important.",
    "Project": "Projeter", "Pension": "Rente",
    "How much eligible pension income to move to the lower earner. Only pension income can move "
    "— a wage cannot, and RRQ has its own separate mechanism.":
        "La part du revenu de pension admissible à transférer au conjoint au revenu le plus bas. "
        "Seul le revenu de pension peut être fractionné — pas un salaire, et le RRQ a son propre "
        "mécanisme.",
    "Today's $": "$ d'aujourd'hui",
    "Show the results in today's purchasing power instead of the dollars of the year they happen. "
    "The projection itself is unchanged — this only divides each year by its inflation factor.":
        "Afficher les résultats en pouvoir d'achat d'aujourd'hui plutôt qu'en dollars de l'année "
        "où ils arrivent. La projection ne change pas — chaque année est seulement divisée par "
        "son facteur d'inflation.",
    "Run projection": "Lancer la projection", "Run many paths": "Lancer plusieurs scénarios",
    "Run the same plan over hundreds of return orderings. One average cannot show sequence risk; "
    "this can.":
        "Faire tourner le même plan sur des centaines d'ordres de rendements. Une moyenne ne "
        "montre pas le risque de séquence; ceci, oui.",
    "Compare start ages": "Comparer les âges de début",
    "Run the plan with each RRQ and PSV started at every age from 65 to 72 (RRQ) or 70 (PSV) and "
    "show what each leaves at the end.":
        "Faire tourner le plan avec la RRQ et la PSV commencées à chaque âge de 65 à 72 (RRQ) ou "
        "70 (PSV), et montrer ce que chacun laisse à la fin.",
    "Key dates": "Dates clés",
    "When to apply for the RRQ and the PSV, the RRSP deadline at 71 and the TFSA's new room - "
    "dated from each person's Born month.":
        "Quand demander la RRQ et la PSV, l'échéance du REER à 71 ans et les nouveaux droits du "
        "CELI - datés selon le mois de naissance de chacun.",
    "Safe budget": "Budget sécuritaire",
    "The most this plan can spend a year to its last age: if every year is average, and in 90% of "
    "simulated return orderings (using the Return and % vol set here).":
        "Le maximum que ce plan peut dépenser par an jusqu'au dernier âge : si chaque année est "
        "moyenne, et dans 90 % des ordres de rendements simulés (avec le Rendement et la % vol "
        "inscrits ici).",
    "Withdrawal order": "Ordre des retraits",
    "Run the plan drawing from REER/FERR, CELI and non-registered accounts in every order, and "
    "compare what is left, the tax paid and the OAS clawback.":
        "Faire tourner le plan en puisant dans le REER/FERR, le CELI et le non enregistré dans "
        "tous les ordres, et comparer ce qui reste, l'impôt payé et la récupération de la PSV.",
    "Best split": "Meilleur fractionnement",
    "Run the plan with 0% to 50% of eligible pension income moved to the lower-income spouse, and "
    "show which leaves the most.":
        "Faire tourner le plan avec 0 % à 50 % du revenu de pension admissible transféré au "
        "conjoint au revenu le plus bas, et montrer lequel laisse le plus.",
    "REER or CELI?": "REER ou CELI?",
    "For money saved now: compare a REER and a CELI with your marginal tax rate now and in the "
    "year it would come out.":
        "Pour l'argent épargné maintenant : comparer un REER et un CELI avec votre taux marginal "
        "aujourd'hui et l'année où il serait retiré.",
    "Draw REER early": "Décaisser le REER tôt",
    "Compare drawing the REER down early - up to a taxable income each year until 71 - with "
    "drawing nothing extra.":
        "Comparer un décaissement hâtif du REER - jusqu'à un revenu imposable donné chaque année "
        "jusqu'à 71 ans - avec aucun retrait supplémentaire.",
    "Save inputs": "Enregistrer les données", "Save sim": "Garder la simulation",
    "Keep the current run on the chart as the line to compare against. It stays there until you "
    "press this again — including after the app is closed.":
        "Garder la simulation actuelle sur le graphique comme ligne de comparaison. Elle y reste "
        "jusqu'à ce que vous cliquiez de nouveau — même après la fermeture de l'application.",
    "Clear saved": "Effacer la simulation gardée", "People": "Personnes", "Age": "Âge",
    "TFSA room": "Droits CELI", "Born": "Naissance", "Add": "Ajouter", "Remove": "Retirer",
    "Accounts": "Comptes", "Balance": "Solde", "Owner": "Titulaire", "Incomes": "Revenus",
    "Income": "Revenu", "Per year": "Par an", "Starts": "Début", "Ends": "Fin", "Indexed": "Indexé",
    "Fill in the tables, then Run projection.": "Remplissez les tableaux, puis Lancer la projection.",
    "Year": "Année", "Ages": "Âges", "RRIF minimum": "Minimum FERR", "Tax": "Impôt",
    "OAS clawback": "Récupération PSV", "From capital": "Du capital", "Reinvested": "Réinvesti",
    "Into TFSA": "Au CELI", "Unfunded": "Non financé", "Closing": "Solde final",
    "Every figure is in the dollars of the year it happens: the return is the nominal one a fund "
    "reports, and inflation is projected rather than netted out of it. So the RRQ, the PSV and "
    "the spending all rise year by year, and so do the tax brackets, which are indexed by law — "
    "if indexation ever stops, this is optimistic. An income you mark Indexed = No keeps paying "
    "the same cheque and quietly loses half its worth over thirty years. Tick Today's $ to read "
    "the whole table in today's purchasing power. A withdrawal from a registered account is "
    "income: covering a gap takes enough more to pay its own tax. Income left over after tax and "
    "spending - a RRIF minimum you did not need, a wage still coming in - is saved, drawn last: "
    "into the TFSA while there is room (each person's room today, in the People table, plus each "
    "year's new limit), the rest in a non-registered account whose growth is taxed every year as "
    "a capital gain. And a single return path says nothing about the order returns arrive in: a "
    "bad first few years of drawing down hurts far more than the same average later. Not "
    "financial advice.":
        "Chaque montant est en dollars de l'année où il arrive : le rendement est le rendement "
        "nominal qu'un fonds publie, et l'inflation est projetée plutôt que retranchée. La RRQ, "
        "la PSV et les dépenses augmentent donc d'année en année, tout comme les paliers d'impôt, "
        "indexés par la loi — si l'indexation cessait, ceci serait optimiste. Un revenu marqué "
        "Indexé = Non verse le même chèque et perd discrètement la moitié de sa valeur en trente "
        "ans. Cochez $ d'aujourd'hui pour lire tout le tableau en pouvoir d'achat d'aujourd'hui. "
        "Un retrait d'un compte enregistré est un revenu : combler un manque demande assez de "
        "plus pour payer son propre impôt. Le revenu qui reste après l'impôt et les dépenses - un "
        "minimum FERR non requis, un salaire qui rentre encore - est épargné et puisé en dernier : "
        "au CELI tant qu'il y a des droits (les droits de chacun aujourd'hui, dans le tableau "
        "Personnes, plus le nouveau plafond de chaque année), le reste dans un compte non "
        "enregistré dont la croissance est imposée chaque année comme gain en capital. Et un seul "
        "scénario de rendement ne dit rien de l'ordre où les rendements arrivent : quelques "
        "mauvaises premières années de décaissement font bien plus mal que la même moyenne plus "
        "tard. Ceci n'est pas un conseil financier.",

    # --- Phase 2: Settings -------------------------------------------------------------------
    "Data source": "Source des données",
    "Where the app gets prices and fundamentals. Switch to Offline (synthetic) to run with no "
    "network (demos/testing) — new data loads use the selected source. The architecture supports "
    "adding more sources (Alpaca, Polygon, IBKR feed) later.":
        "D'où l'application tire les prix et les données fondamentales. Passez à Hors ligne "
        "(synthétique) pour fonctionner sans réseau (démos, tests) — les nouveaux chargements "
        "utilisent la source choisie. D'autres sources (Alpaca, Polygon, flux IBKR) pourront "
        "s'ajouter plus tard.",
    "Provider": "Fournisseur",
    "Live prices & fundamentals via Yahoo (yfinance); synthetic fallback if a symbol fails.":
        "Prix et données fondamentales en direct par Yahoo (yfinance); données synthétiques si un "
        "symbole échoue.",
    "Data refresh": "Actualisation des données",
    "When you open a tab, its data is fetched again if it has gone stale. Prices, book value and "
    "the market read go stale after the time below; dividends, sectors and the retirement indices "
    "once a day, because nothing in them moves during a session. The ETF Screener, and anything "
    "you run yourself - scans, backtests, projections - never refresh on their own.":
        "Quand vous ouvrez un onglet, ses données sont récupérées de nouveau si elles sont "
        "périmées. Les prix, la valeur des comptes et la lecture du marché se périment après le "
        "délai ci-dessous; les dividendes, les secteurs et les indices de retraite une fois par "
        "jour, car rien n'y bouge pendant une séance. Le filtre de FNB, et tout ce que vous lancez "
        "vous-même - balayages, tests historiques, projections - ne s'actualisent jamais seuls.",
    "Refresh a tab when it is opened, if older than":
        "Actualiser un onglet à l'ouverture, s'il date de plus de",
    "Updates": "Mises à jour",
    "TradeLab looks for a newer installer in the folder below (where new versions are built - "
    "TradeLabPro\\installer\\Output) and offers to install it in one click; it also checks which "
    "version is published on GitHub.":
        "TradeLab cherche un installateur plus récent dans le dossier ci-dessous (où les "
        "nouvelles versions sont construites - TradeLabPro\\installer\\Output) et offre de "
        "l'installer en un clic; il vérifie aussi quelle version est publiée sur GitHub.",
    "Installer folder": "Dossier de l'installateur",
    "Folder holding TradeLabPro-Setup-X.Y.Z.exe": "Dossier contenant TradeLabPro-Setup-X.Y.Z.exe",
    "Browse…": "Parcourir…", "Check now": "Vérifier maintenant",
    "Check when TradeLab starts": "Vérifier au démarrage de TradeLab",
    "Backups": "Sauvegardes",
    "Once a week TradeLab copies your data (portfolios, cash, journal, retirement plan, alerts, "
    "links, notes) into a zip in the backups folder; the last 8 are kept. To restore, close "
    "TradeLab, unzip a backup and copy its files back into the data folder.":
        "Une fois par semaine, TradeLab copie vos données (portefeuilles, liquidités, journal, "
        "plan de retraite, alertes, liens, notes) dans un fichier zip du dossier de sauvegardes; "
        "les 8 dernières sont gardées. Pour restaurer, fermez TradeLab, décompressez une "
        "sauvegarde et recopiez ses fichiers dans le dossier de données.",
    "Back up now": "Sauvegarder maintenant", "Restore…": "Restaurer…",
    "Open backup folder": "Ouvrir le dossier des sauvegardes", "No backup yet.": "Aucune sauvegarde.",

    # --- Phase 3: the Advanced tabs ----------------------------------------------------------
    # Market
    "Market Dashboard": "Tableau de bord du marché",
    "11 GICS sectors (SPDR select-sector ETFs) vs SPY.":
        "11 secteurs GICS (FNB sectoriels SPDR) comparés à SPY.",
    "Refresh market dashboard": "Actualiser le tableau de bord",
    "Click any index, regime symbol or sector below to chart it.":
        "Cliquez un indice, un symbole de régime ou un secteur ci-dessous pour voir son graphique.",
    "Is it a good day to trade US?": "Est-ce une bonne journée pour négocier aux États-Unis?",
    "Refresh to compute the read.": "Actualisez pour calculer la lecture.",
    "Market breadth — advance / decline": "Ampleur du marché — hausses / baisses",
    "How broad the move is across individual stocks, not just the index. A durable trend has most "
    "stocks above their 200-day average; a thin, top-heavy rally does not.":
        "L'étendue du mouvement parmi les titres, pas seulement l'indice. Une tendance durable a la "
        "plupart des titres au-dessus de leur moyenne de 200 jours; une hausse étroite, portée par "
        "quelques géants, non.",
    "of stocks above their 200-day average": "des titres au-dessus de leur moyenne de 200 jours",
    "Global indices — which markets are favorable (in market-open order)":
        "Indices mondiaux — quels marchés sont favorables (dans l'ordre d'ouverture)",
    "Listed in trading-session order: Tokyo → Hong Kong → London/Frankfurt → New York/Toronto.\n"
    "Read = position vs the 50- and 200-day averages: above both = Favorable, below both = "
    "Caution, mixed = Neutral.":
        "Dans l'ordre des séances : Tokyo → Hong Kong → Londres/Francfort → New York/Toronto.\n"
        "Lecture = position par rapport aux moyennes de 50 et 200 jours : au-dessus des deux = "
        "Favorable, sous les deux = Prudence, mixte = Neutre.",
    "Last": "Dernier", "vs 50-day": "vs 50 jours", "vs 200-day": "vs 200 jours", "Read": "Lecture",
    "Click a row to chart that symbol.": "Cliquez une ligne pour voir le graphique de ce symbole.",
    "US regime symbols": "Symboles de régime américains", "Item": "Élément", "Purpose": "Rôle",
    "US sector favorability — which sectors to trade (best → worst)":
        "Secteurs américains favorables — lesquels négocier (du meilleur au pire)",
    "How this is scored ▾": "Comment c'est noté ▾",
    "How the sector score is computed": "Comment la note sectorielle est calculée",
    "Sector": "Secteur", "RS vs SPY": "FR vs SPY", "Score / Read": "Note / Lecture",
    "Refresh to update the dashboard. Data uses yfinance when available.":
        "Actualisez pour mettre le tableau de bord à jour. Les données viennent de yfinance quand "
        "c'est possible.",
    # Heatmap
    "A market map at a glance. Each tile is a stock/ETF, sized by market cap and coloured by its % "
    "change over the selected Period (green up, red down), grouped by Sector, Industry or Country. "
    "Map a preset, a Theme basket, the World, your Watchlist or Portfolio. Click a tile to chart "
    "it, right-click for more. Scroll to zoom in on small tiles, drag to pan, double-click to fit.":
        "Une carte du marché en un coup d'œil. Chaque tuile est un titre ou un FNB, dimensionné "
        "selon sa capitalisation et coloré selon sa variation sur la période choisie (vert en "
        "hausse, rouge en baisse), regroupé par secteur, industrie ou pays. Cartographiez un "
        "préréglage, un thème, le monde, votre liste de suivi ou votre portefeuille. Cliquez une "
        "tuile pour son graphique, clic droit pour plus. Molette pour zoomer, glisser pour "
        "déplacer, double-clic pour ajuster.",
    "Map a thematic basket (AI, Semiconductors, EV, …). Overrides Market while set.":
        "Cartographier un panier thématique (IA, semi-conducteurs, VÉ, …). Remplace le marché "
        "tant qu'il est choisi.",
    "Performance window the tile colour represents (like Finviz): 1 Day, 1 Week … 10 Year, YTD.":
        "Période que représente la couleur des tuiles (comme Finviz) : 1 jour, 1 semaine … 10 ans, "
        "depuis le début de l'année.",
    "Size by": "Taille selon", "Group": "Grouper", "Theme": "Thème", "Watchlist": "Liste de suivi",
    "Tile area = market cap (classic) or today's traded dollar volume (faster, no cap lookup).":
        "Surface des tuiles = capitalisation (classique) ou volume négocié en dollars aujourd'hui "
        "(plus rapide, sans recherche de capitalisation).",
    "Group tiles into blocks by Sector, Industry, or Country (Country suits the World map).":
        "Regrouper les tuiles en blocs par secteur, industrie ou pays (le pays convient à la carte "
        "du monde).",
    "Cap the number of tiles (largest first) so the map stays fast and readable.":
        "Limiter le nombre de tuiles (les plus grandes d'abord) pour que la carte reste rapide et "
        "lisible.",
    "Load map": "Charger la carte", "Auto-refresh every": "Actualiser automatiquement toutes les",
    "Reload the map on a timer so it tracks the market during the day.":
        "Recharger la carte à intervalle régulier pour suivre le marché pendant la journée.",
    "Pick a market and click Load map.": "Choisissez un marché et cliquez Charger la carte.",
    # News
    "Recent headlines by source: a Symbol, the broad Market, a Sector, or Geopolitical news. "
    "Macro/political stories (Fed, inflation, elections, tariffs, war, OPEC…) are flagged ⚑ — a "
    "light stand-in for a full economic/political calendar. Double-click a headline to open it in "
    "your browser.":
        "Les manchettes récentes par source : un symbole, le marché, un secteur ou la géopolitique. "
        "Les nouvelles macro et politiques (Fed, inflation, élections, tarifs, guerre, OPEP…) sont "
        "signalées ⚑ — un substitut léger à un calendrier économique complet. Double-cliquez une "
        "manchette pour l'ouvrir dans votre navigateur.",
    "Macro / political only": "Macro / politique seulement", "Get news": "Obtenir les nouvelles",
    "Time": "Heure", "Headline": "Manchette", "Tickers": "Symboles",
    "Pick a source and click Get news.": "Choisissez une source et cliquez Obtenir les nouvelles.",
    # Scanner
    "New": "Nouveau", "Create a new scanner setup from default values":
        "Créer un nouveau réglage du scanneur à partir des valeurs par défaut",
    "Open": "Ouvrir",
    "Open a setup file from elsewhere on disk. To switch between your saved presets, use the "
    "Preset dropdown instead.":
        "Ouvrir un fichier de réglage ailleurs sur le disque. Pour passer d'un préréglage "
        "enregistré à l'autre, utilisez plutôt la liste Préréglage.",
    "Save the current scanner setup": "Enregistrer le réglage actuel du scanneur",
    "Save As": "Enregistrer sous", "Save the current scanner setup to a chosen file":
        "Enregistrer le réglage actuel dans un fichier choisi",
    "Duplicate": "Dupliquer", "Duplicate this setup name so you can save a variation":
        "Dupliquer ce nom de réglage pour enregistrer une variante",
    "Delete": "Supprimer", "Delete the setup file with the current setup name":
        "Supprimer le fichier de réglage portant ce nom",
    "Reset": "Réinitialiser", "Reset controls to the default professional swing setup":
        "Remettre les contrôles au réglage professionnel par défaut",
    "Hide filters": "Masquer les filtres", "Preset:": "Préréglage :",
    "Pick a saved preset to switch instantly, or type a new name to Save/Save As under it.":
        "Choisissez un préréglage pour l'activer aussitôt, ou tapez un nouveau nom pour "
        "Enregistrer/Enregistrer sous.",
    "Scanner Parameters": "Paramètres du scanneur", "General": "Général", "Scan name": "Nom du balayage",
    "Exchange preset": "Bourses",
    "Which universe to scan. 'Sectors — US' / 'Sectors — Canada' list that market's curated "
    "sector, sub-sector (gold, banks, uranium…) and ETF baskets; the two are never shown together.":
        "Quel univers balayer. « Sectors — US » / « Sectors — Canada » listent les paniers de "
        "secteurs, sous-secteurs (or, banques, uranium…) et FNB de ce marché; les deux ne sont "
        "jamais affichés ensemble.",
    "Strategy": "Stratégie",
    "Which strategy scores/signals each symbol (includes your no-code custom strategies).":
        "Quelle stratégie note et signale chaque symbole (y compris vos stratégies sans code).",
    "Interval": "Intervalle", "Maximum symbols (0 = all)": "Nombre maximal de symboles (0 = tous)",
    "0 = scan all selected symbols. Use 50/100 for a fast test.":
        "0 = balayer tous les symboles choisis. Utilisez 50 ou 100 pour un test rapide.",
    "Price / Volume": "Prix / Volume", "Minimum price": "Prix minimal",
    "Minimum last price. Example default: $5.00.": "Dernier prix minimal. Par défaut : 5,00 $.",
    "Maximum price": "Prix maximal",
    "Maximum last price. Leave high to avoid limiting expensive stocks.":
        "Dernier prix maximal. Laissez-le élevé pour ne pas exclure les titres chers.",
    "Minimum volume": "Volume minimal",
    "Minimum current period volume. Use 500,000+ to avoid illiquid stocks.":
        "Volume minimal de la période. Utilisez 500 000 ou plus pour éviter les titres peu liquides.",
    "Minimum market cap": "Capitalisation minimale",
    "Minimum market capitalization in billions. Example: 2 = $2B.":
        "Capitalisation minimale en milliards. Exemple : 2 = 2 G$.",
    "Minimum relative volume": "Volume relatif minimal",
    "Relative volume = current volume / 20-period average volume. 0 disables this filter.":
        "Volume relatif = volume actuel / volume moyen sur 20 périodes. 0 désactive ce filtre.",
    "Technical": "Technique", "Minimum RSI": "RSI minimal",
    "Minimum RSI14. 0 disables the lower bound.": "RSI14 minimal. 0 désactive la borne inférieure.",
    "Maximum RSI": "RSI maximal",
    "Maximum RSI14. 100 disables the upper bound.": "RSI14 maximal. 100 désactive la borne supérieure.",
    "Minimum ATR %": "ATR % minimal",
    "Minimum ATR as percent of price. 0 disables this filter.":
        "ATR minimal en pourcentage du prix. 0 désactive ce filtre.",
    "Maximum ATR %": "ATR % maximal",
    "Maximum ATR as percent of price. 100 disables this filter.":
        "ATR maximal en pourcentage du prix. 100 désactive ce filtre.",
    "Signal / Score": "Signal / Note", "Minimum score": "Note minimale",
    "Minimum scanner score from 0 to 100. Higher scores are stricter.":
        "Note minimale du scanneur, de 0 à 100. Plus elle est haute, plus le filtre est strict.",
    "Require EMA trend": "Exiger la tendance EMA", "EMA fast above EMA slow": "EMA rapide au-dessus de l'EMA lente",
    "Require MACD bullish": "Exiger un MACD haussier", "MACD above signal": "MACD au-dessus du signal",
    "Custom Filters": "Filtres personnalisés", "+ Add Filter": "+ Ajouter un filtre",
    "Add a condition on any technical field (price, RSI, MACD, EMA, ADX, Bollinger, etc.)":
        "Ajouter une condition sur un champ technique (prix, RSI, MACD, EMA, ADX, Bollinger, etc.)",
    "Exchanges / My Lists": "Bourses / Mes listes", "Refresh exchanges": "Actualiser les bourses",
    "Create My List": "Créer une liste",
    "Select every sector / industry / ETF basket shown":
        "Choisir tous les paniers de secteurs, d'industries et de FNB affichés",
    "Select NYSE + NASDAQ + AMEX": "Choisir NYSE + NASDAQ + AMEX",
    "Select TSX + TSXV + CSE": "Choisir TSX + TSXV + CSE", "All": "Tout",
    "Select all exchanges and lists shown": "Choisir toutes les bourses et listes affichées",
    "Clear all exchange/list selections": "Effacer tous les choix de bourses et de listes",
    "START SCAN": "LANCER LE BALAYAGE", "STOP": "ARRÊTER",
    "Ready. Exchange lists auto-refresh when the cache is old or after a refresh button press.":
        "Prêt. Les listes des bourses s'actualisent seules quand le cache est vieux ou après un "
        "clic sur Actualiser.",
    "Scan Status": "État du balayage", "Current": "En cours", "Scanned": "Balayés",
    "Matches": "Correspondances", "Elapsed": "Écoulé", "ETA": "Reste", "Score": "Note",
    "Sample": "Échantillon", "Volume": "Volume", "RelVol": "VolRel", "Market Cap": "Capitalisation",
    "Cap": "Cap.", "Add selected to Watchlist": "Ajouter la sélection à la liste de suivi",
    "Add selected to Portfolio": "Ajouter la sélection au portefeuille",
    "🗺 Map results": "🗺 Carte des résultats",
    "Show the scan results as a heatmap (sized by cap, coloured by % change).":
        "Afficher les résultats en carte thermique (taille selon la capitalisation, couleur "
        "selon la variation).",
    "Export results CSV": "Exporter les résultats (CSV)", "⛶ Full screen": "⛶ Plein écran",
    "Give the whole window to this table, hiding the chart. Click again to put it back.":
        "Donner toute la fenêtre à ce tableau en masquant le graphique. Cliquez de nouveau pour "
        "le remettre.",
    # ETF Screener
    "Ticker (e.g. VFV)": "Symbole (ex. VFV)", "Yahoo symbol (e.g. VFV.TO)": "Symbole Yahoo (ex. VFV.TO)",
    "The symbol Yahoo Finance knows it by. TSX listings end in .TO. Leave empty to reuse the ticker.":
        "Le symbole connu de Yahoo Finance. Les titres du TSX finissent par .TO. Laissez vide pour "
        "reprendre le symbole.",
    "Narrow to one category, region, account or currency. Built from what the table actually "
    "contains.":
        "Restreindre à une catégorie, une région, un compte ou une devise. Construit à partir de "
        "ce que contient le tableau.",
    "Filter…": "Filtrer…",
    "Show only funds whose ticker, name, category or region contains this text.":
        "Afficher seulement les fonds dont le symbole, le nom, la catégorie ou la région contient "
        "ce texte.",
    "Refresh returns & risk": "Actualiser rendements et risque",
    "Downloads 11 years of history per fund (Yahoo Finance) and recomputes returns and risk. Never "
    "overwrites anything you typed.":
        "Télécharge 11 ans d'historique par fonds (Yahoo Finance) et recalcule les rendements et "
        "le risque. N'écrase jamais ce que vous avez tapé.",
    "Stop": "Arrêter",
    "Adds the fund at 0 shares, ready for you to enter what you hold on the Portfolio tab.":
        "Ajoute le fonds à 0 part, prêt pour inscrire ce que vous détenez dans l'onglet "
        "Portefeuille.",
    "Compare selected": "Comparer la sélection",
    "Plots the selected funds on one chart, each restated to 100 at the first date they all share.":
        "Trace les fonds choisis sur un même graphique, chacun ramené à 100 à la première date "
        "qu'ils ont en commun.",
    "Allocation:": "Répartition :", "Low risk": "Risque faible", "Mid risk": "Risque moyen",
    "High risk": "Risque élevé",
    "Which allocation the analyses below act on.": "La répartition sur laquelle portent les analyses ci-dessous.",
    "Build…": "Construire…",
    "Fill the selected allocation column by a rule you set: which risk bands count, equal or "
    "inverse-volatility weighting, a cap per fund.":
        "Remplir la colonne de répartition choisie selon une règle : quels niveaux de risque "
        "comptent, pondération égale ou inverse de la volatilité, plafond par fonds.",
    "Target vs held": "Cible vs détenu",
    "Compares this allocation against the positions on your Portfolio tab and reports the gap in "
    "dollars.":
        "Compare cette répartition aux positions de l'onglet Portefeuille et donne l'écart en "
        "dollars.",
    "What this mix holds": "Ce que contient ce mélange",
    "Opens every fund in the allocation up to the companies inside it, so the same name held twice "
    "shows once.":
        "Ouvre chaque fonds de la répartition jusqu'aux sociétés qu'il contient, pour qu'un même "
        "nom détenu deux fois n'apparaisse qu'une fois.",
    "What each fund holds": "Ce que contient chaque fonds",
    "Every fund and what is inside it, one row per holding — all of them, not just the allocation.":
        "Chaque fonds et ce qu'il contient, une ligne par titre — tous, pas seulement la "
        "répartition.",
    "Export CSV": "Exporter (CSV)", "Ticker": "Symbole", "Category": "Catégorie", "Region": "Région",
    "Exchange": "Bourse", "% Bonds": "% Obligations", "% Commodity": "% Marchandises",
    "Div %/yr": "Div. %/an", "Volatility": "Volatilité", "Worst drop": "Pire baisse",
    "Updated": "Mis à jour",
    "Each allocation column adds up here. 100% means fully allocated.":
        "Chaque colonne de répartition s'additionne ici. 100 % veut dire entièrement réparti.",
    "What each allocation holds": "Ce que contient chaque répartition",
    "Type percentages the way you say them (20 = 20%). A figure followed by \"of X% of the "
    "allocation\" stands on that much of it — funds missing the figure are left out rather than "
    "counted as zero. Analysis, not financial advice.":
        "Tapez les pourcentages comme vous les dites (20 = 20 %). Un chiffre suivi de « de X % de "
        "la répartition » ne porte que sur cette part — les fonds sans ce chiffre sont laissés "
        "de côté plutôt que comptés à zéro. Analyse, pas un conseil financier.",
    # Watchlists
    "AAPL or RY.TO": "AAPL ou RY.TO", "Import": "Importer",
    # Alerts
    "Get notified when a symbol meets a condition. Alerts are edge-triggered: 'RSI Below 30' fires "
    "once as it drops through 30, not every check. Analysis tool only - alerts never place orders.":
        "Soyez averti quand un symbole remplit une condition. Les alertes se déclenchent au "
        "franchissement : « RSI sous 30 » sonne une fois quand il passe sous 30, pas à chaque "
        "vérification. Outil d'analyse seulement - une alerte ne passe jamais d'ordre.",
    "New alert": "Nouvelle alerte", "Symbol e.g. AAPL": "Symbole ex. AAPL", "from list": "de la liste",
    "Pick a symbol from your watchlist": "Choisir un symbole dans votre liste de suivi",
    "recurring: re-arms and can fire again on the next crossing.\nonce: fires a single time, then "
    "turns itself off.":
        "recurring : se réarme et peut sonner au prochain franchissement.\nonce : sonne une seule "
        "fois, puis se désactive.",
    "Bars": "Barres", "Bar interval the condition is evaluated on.":
        "Intervalle des barres sur lequel la condition est évaluée.",
    "When": "Quand", "Add alert": "Ajouter l'alerte", "Condition": "Condition", "Status": "État",
    "Last price": "Dernier prix", "Fired": "Déclenchée", "Enable / Disable": "Activer / Désactiver",
    "Auto-check every": "Vérifier automatiquement toutes les", "Triggered alerts:": "Alertes déclenchées :",
    # AI Assist
    "Natural-language assistant. It explains indicators, scores and setups in plain English. "
    "Educational only — not financial advice. Uses your own Anthropic API key (per-use cost billed "
    "to you); with no key it falls back to the offline rules-based Trade Coach.":
        "Assistant en langage courant. Il explique les indicateurs, les notes et les "
        "configurations. Éducatif seulement — pas un conseil financier. Utilise votre propre clé "
        "API Anthropic (coût par utilisation facturé à vous); sans clé, il se rabat sur le Coach "
        "hors ligne fondé sur des règles.",
    "⚠ No live market data. Answers are based on the indicators TradeLabPro computes for the loaded "
    "symbol plus the model's general knowledge (not real-time). It cannot give current prices, "
    "today's news, or earnings dates. Educational only — not financial advice.":
        "⚠ Aucune donnée de marché en direct. Les réponses reposent sur les indicateurs que "
        "TradeLabPro calcule pour le symbole chargé et sur les connaissances générales du modèle "
        "(pas en temps réel). Il ne peut donner ni les prix actuels, ni les nouvelles du jour, ni "
        "les dates de résultats. Éducatif seulement — pas un conseil financier.",
    "API key": "Clé API",
    "Anthropic API key (sk-ant-...) - stored locally on this machine":
        "Clé API Anthropic (sk-ant-...) - gardée sur cet ordinateur",
    "Model": "Modèle", "AI mode: off (no key) - answers use the offline Trade Coach.":
        "Mode IA : désactivé (aucune clé) - les réponses viennent du Coach hors ligne.",
    "Load symbol context": "Charger le contexte du symbole",
    "Shortlist check - compare candidates side by side":
        "Vérification d'une courte liste - comparer les candidats côte à côte",
    "Symbols, e.g. XEQT.TO VEQT.TO XBB.TO VTI": "Symboles, ex. XEQT.TO VEQT.TO XBB.TO VTI",
    "(then)": "(puis)", "Check all": "Tout vérifier", "Explain with AI": "Expliquer avec l'IA",
    "Worst fall": "Pire baisse", "5 yr/yr": "5 ans/an", "10 yr/yr": "10 ans/an",
    "Overlap": "Chevauchement",
    "The candidate check's facts for each symbol, ordered by what you choose. Explain with AI "
    "describes what stands out - it never says what to buy. Not financial advice.":
        "Les faits de la vérification pour chaque symbole, triés selon votre choix. Expliquer "
        "avec l'IA décrit ce qui ressort - il ne dit jamais quoi acheter. Pas un conseil financier.",
    "Ask about a symbol, indicator or setup...": "Posez une question sur un symbole, un indicateur ou une configuration...",
    "Send": "Envoyer", "Clear": "Effacer",
    # Risk
    "Size a trade by risk, not by gut: set how much of your account you'll risk and where your "
    "stop is, and get the share count that risks exactly that. See your R-multiple targets and how "
    "concentrated your portfolio is by sector. Planning tool only — it places no orders.":
        "Dimensionnez une transaction selon le risque, pas à l'instinct : fixez la part de votre "
        "compte que vous risquez et votre arrêt, et obtenez le nombre de parts qui risque "
        "exactement cela. Voyez vos cibles en multiples de R et la concentration de votre "
        "portefeuille par secteur. Outil de planification seulement — aucun ordre n'est passé.",
    "Position sizing": "Taille de position", "Account equity": "Avoir du compte",
    "Risk per trade": "Risque par transaction", "Side": "Sens", "Entry price": "Prix d'entrée",
    "Stop price": "Prix d'arrêt", "Max position": "Position maximale",
    "Optional cap on position size as % of account (0 = off).":
        "Plafond facultatif de la position en % du compte (0 = aucun).",
    "Use paper account equity": "Utiliser l'avoir du compte simulé",
    "Fill Account equity from your paper-trading account.":
        "Remplir l'avoir du compte à partir de votre compte de négociation simulée.",
    "Targets (R = your stop distance):": "Cibles (R = distance de votre arrêt) :",
    "Target price": "Prix cible", "$ / share": "$ / part", "Position $": "Position $",
    "Portfolio sector exposure": "Exposition sectorielle du portefeuille",
    "Load portfolio exposure": "Charger l'exposition du portefeuille",
    "% of portfolio": "% du portefeuille",
    "Positions come from the Portfolio tab.": "Les positions viennent de l'onglet Portefeuille.",
    # Paper trading
    "PAPER TRADING — simulated account. No real money, no live orders are ever placed. For "
    "practice and testing only.":
        "NÉGOCIATION SIMULÉE — compte fictif. Aucun argent réel, aucun ordre réel n'est jamais "
        "passé. Pour la pratique et les tests seulement.",
    "Qty": "Qté", "Limit": "Limite", "Trail": "Suivi", "Place order": "Passer l'ordre",
    "Bracket:": "Ordres liés :",
    "Attach a take-profit and/or stop-loss to a Market or Limit entry (one cancels the other).":
        "Joindre une prise de profit et/ou un arrêt de perte à une entrée au marché ou à cours "
        "limité (l'un annule l'autre).",
    "Take-profit": "Prise de profit", "Stop-loss": "Arrêt de perte",
    "0 = leave that exit off. Bracket uses a Market or Limit entry.":
        "0 = pas de cette sortie. Les ordres liés utilisent une entrée au marché ou à cours limité.",
    "Refresh (mark-to-market + trigger stops/limits)":
        "Actualiser (évaluer au marché + déclencher arrêts et limites)",
    "Cancel selected order": "Annuler l'ordre choisi", "Reset account": "Réinitialiser le compte",
    "Positions": "Positions", "Avg price": "Prix moyen", "Mkt value": "Valeur marchande",
    "Orders": "Ordres", "Fill price": "Prix d'exécution",
    # Analytics
    "Risk analytics for your Portfolio-tab holdings, viewed as one book. Enter a benchmark and "
    "history window and click Analyze: the app values every position, measures the portfolio's "
    "beta, volatility, drawdown and return against the benchmark, shows how concentrated it is, and "
    "how correlated the holdings are. Add positions in the Portfolio tab first. Analysis only — no "
    "live orders.":
        "Analyse du risque des titres de l'onglet Portefeuille, vus comme un tout. Inscrivez un "
        "indice de référence et une période, puis cliquez Analyser : l'application évalue chaque "
        "position, mesure le bêta, la volatilité, la baisse maximale et le rendement par rapport "
        "à l'indice, montre la concentration et la corrélation des titres. Ajoutez d'abord des "
        "positions dans l'onglet Portefeuille. Analyse seulement — aucun ordre réel.",
    "Benchmark": "Indice de référence", "History": "Historique", "Analyze": "Analyser",
    "Add holdings in the Portfolio tab, then click Analyze.":
        "Ajoutez des titres dans l'onglet Portefeuille, puis cliquez Analyser.",
    "Total value": "Valeur totale", "Return vs bench": "Rendement vs indice", "Beta": "Bêta",
    "Ann. volatility": "Volatilité annuelle", "Max drawdown": "Baisse maximale",
    "Holdings": "Titres", "Ccy": "Devise", "Avg entry": "Entrée moyenne", "Weight %": "Poids %",
    "Unreal P&L": "Gain/perte latent", "Unreal %": "Latent %",
    "Look-through exposure (funds opened up)": "Exposition transparente (fonds ouverts)",
    "Click Analyze to read your holdings through to the companies inside them.":
        "Cliquez Analyser pour voir vos titres jusqu'aux sociétés qu'ils contiennent.",
    "Company": "Société", "Exposure": "Exposition", "% of book": "% du total",
    "Held directly": "Détenu directement", "Also inside": "Aussi dans",
    "Your book by company instead of by position: a stock you own outright and also hold inside a "
    "fund appears once, with both parts added together.\nClick a row to chart it.":
        "Vos placements par société plutôt que par position : un titre détenu directement et "
        "aussi dans un fonds n'apparaît qu'une fois, les deux parts additionnées.\nCliquez une "
        "ligne pour son graphique.",
    "Correlation (daily returns)": "Corrélation (rendements quotidiens)",
    "Correlation of daily returns between holdings. Red = they move together (concentrated risk); "
    "green = they diversify each other.":
        "Corrélation des rendements quotidiens entre les titres. Rouge = ils bougent ensemble "
        "(risque concentré); vert = ils se diversifient.",
    "Risk analysis of holdings you record — not a live brokerage view and not financial advice.":
        "Analyse du risque des titres que vous inscrivez — pas une vue en direct du courtier ni un "
        "conseil financier.",
    # Dividends
    "The income your holdings actually pay. Reads the Portfolio tab and shows each position's "
    "annual dividend, its yield at today's price versus the yield on what you paid, how often it "
    "pays, whether the payout is growing, and a month-by-month calendar of when the money arrives. "
    "Reporting only — not financial advice.":
        "Le revenu que vos titres versent vraiment. Lit l'onglet Portefeuille et montre le "
        "dividende annuel de chaque position, son rendement au prix du jour comparé au rendement "
        "sur ce que vous avez payé, sa fréquence, si le versement augmente, et un calendrier mois "
        "par mois de l'arrivée de l'argent. Rapport seulement — pas un conseil financier.",
    "Add holdings in the Portfolio tab, then click Refresh.":
        "Ajoutez des titres dans l'onglet Portefeuille, puis cliquez Actualiser.",
    "Average per month": "Moyenne par mois", "Portfolio yield": "Rendement du portefeuille",
    "Yield on cost": "Rendement sur le coût", "Paying holdings": "Titres qui versent",
    "Income by holding": "Revenu par titre", "Pays": "Verse", "Div/share (yr)": "Div./part (an)",
    "Yield": "Rendement", "On cost": "Sur le coût", "When it arrives": "Quand il arrive",
    "Month": "Mois", "Expected income": "Revenu attendu", "From": "De",
    "Projected from the months each holding paid in over the last year, at the current rate.":
        "Projeté selon les mois où chaque titre a versé l'an dernier, au taux actuel.",
    "Projected from past payments — dividends can be cut or raised at any time. Reporting only — "
    "not financial advice.":
        "Projeté à partir des versements passés — un dividende peut être réduit ou augmenté en "
        "tout temps. Rapport seulement — pas un conseil financier.",
    # Retirement
    "A workplace plan the app can't connect to — a group RRSP, a pension. Paste the fund table from "
    "your statement and each fund is measured against the others and against an index. Two "
    "statement dates are what turn a balance into a return, so the first paste starts the clock "
    "and the next one answers the question. Reporting only — not financial advice.":
        "Un régime d'employeur auquel l'application ne peut se connecter — un REER collectif, un "
        "régime de retraite. Collez le tableau des fonds de votre relevé et chaque fonds est "
        "comparé aux autres et à un indice. Il faut deux dates de relevé pour qu'un solde "
        "devienne un rendement : le premier collage démarre le chronomètre, le suivant répond. "
        "Rapport seulement — pas un conseil financier.",
    "New plan": "Nouveau régime", "Rename": "Renommer",
    "Create a plan, then paste your statement below.":
        "Créez un régime, puis collez votre relevé ci-dessous.",
    "Plan value": "Valeur du régime", "Gain since first statement": "Gain depuis le premier relevé",
    "Best fund": "Meilleur fonds", "Weakest fund": "Fonds le plus faible", "Funds": "Fonds",
    "Enter a statement": "Inscrire un relevé",
    "Copy the fund table straight off your plan's website and paste it here — one fund per line. "
    "Two numbers on a line are read as units and unit value; one is read as a balance. Category "
    "headings are ignored.":
        "Copiez le tableau des fonds directement du site de votre régime et collez-le ici — un "
        "fonds par ligne. Deux nombres sur une ligne sont lus comme unités et valeur unitaire; un "
        "seul comme un solde. Les titres de catégorie sont ignorés.",
    "Statement date": "Date du relevé", "YYYY-MM-DD": "AAAA-MM-JJ", "Save to plan": "Enregistrer au régime",
    "Paste a statement and click Read.": "Collez un relevé et cliquez Lire.",
    "Published fund returns (from your fund fact sheets)":
        "Rendements publiés des fonds (selon vos fiches de fonds)",
    "Your plan publishes each fund against its own benchmark. Paste a sheet's 'compound returns' "
    "table — the header row plus the Fonds/Indice rows — and pick the fund it belongs to. These "
    "returns are struck before the plan's investment management fee, so set that fee to see what's "
    "left after what you pay.":
        "Votre régime publie chaque fonds par rapport à son propre indice. Collez le tableau des "
        "« rendements composés » d'une fiche — la ligne d'en-tête et les lignes Fonds/Indice — et "
        "choisissez le fonds auquel il appartient. Ces rendements sont calculés avant les frais "
        "de gestion du régime; inscrivez ces frais pour voir ce qui reste après ce que vous payez.",
    "Read sheet": "Lire la fiche", "Plan fee %": "Frais du régime %",
    "The plan's annual investment management fee, which fund fact sheet returns are struck before. "
    "Applied to every fund unless one carries its own.":
        "Les frais annuels de gestion du régime, déduits après les rendements des fiches. "
        "Appliqués à chaque fonds, sauf s'il a les siens.",
    "Horizon": "Horizon", "Compare the fees with": "Comparer les frais avec",
    "A low-cost index fund's yearly fee - yours to set.":
        "Les frais annuels d'un fonds indiciel à faible coût - à vous de les fixer.",
    "at a return before fees of": "à un rendement avant frais de", "Weight": "Poids",
    "Its benchmark": "Son indice", "Excess": "Écart", "Fee": "Frais", "After fee": "Après frais",
    "Your funds": "Vos fonds", "Units": "Unités", "Unit value": "Valeur unitaire",
    "Fund return": "Rendement du fonds", "Over": "Sur", "Your return": "Votre rendement",
    "Index": "Indice", "vs index": "vs indice",
    "Each fund since your first statement (rebased to 100)":
        "Chaque fonds depuis votre premier relevé (ramené à 100)",
    "No plan yet.": "Aucun régime.", "Contributions and withdrawals": "Cotisations et retraits",
    "Only needed for 'Your return'. Money moved before your first statement is already inside that "
    "balance and should not be entered again.":
        "Seulement pour « Votre rendement ». L'argent déplacé avant votre premier relevé est déjà "
        "dans ce solde et ne doit pas être inscrit de nouveau.",
    "Contribution (you)": "Cotisation (vous)", "Employer": "Employeur",
    "Your own figures, recalculated — not a statement from your plan. Not financial advice.":
        "Vos propres chiffres, recalculés — pas un relevé de votre régime. Pas un conseil financier.",
    # Journal
    "Log your trades, tag them, and review what works: win rate, average R-multiple, expectancy, "
    "and P&L by strategy/tag. Set a Stop to get R-multiples. Import round-trips from Paper Trading. "
    "Practice tool only.":
        "Inscrivez vos transactions, étiquetez-les et voyez ce qui fonctionne : taux de réussite, "
        "multiple de R moyen, espérance et gain/perte par stratégie ou étiquette. Inscrivez un "
        "arrêt pour obtenir les multiples de R. Importez les allers-retours de la négociation "
        "simulée. Outil de pratique seulement.",
    "Log a trade": "Inscrire une transaction",
    "Protective stop (0 = none). Needed for R-multiples.":
        "Arrêt de protection (0 = aucun). Nécessaire pour les multiples de R.",
    "Tags": "Étiquettes", "tags, comma-separated": "étiquettes, séparées par des virgules",
    "Entry date": "Date d'entrée", "Exit": "Sortie", "Exit date": "Date de sortie",
    "P&L": "Gain/perte", "P&L %": "Gain/perte %", "Days": "Jours",
    "Click a column header to sort; click again to reverse.":
        "Cliquez un en-tête de colonne pour trier; de nouveau pour inverser.",
    "Close selected…": "Fermer la sélection…", "Edit note…": "Modifier la note…",
    "Import from Paper Trading": "Importer de la négociation simulée",
    "Import from IBKR (CSV)…": "Importer d'IBKR (CSV)…",
    "Import an IBKR trades CSV — a Flex Query 'Trades' export or an Activity Statement.":
        "Importer un CSV de transactions IBKR — un export « Trades » d'une requête Flex ou un "
        "relevé d'activité.",
    "Import from IBKR (Flex)…": "Importer d'IBKR (Flex)…",
    "Fetch your Flex Query report directly over IBKR's Flex Web Service (read-only).":
        "Récupérer votre rapport de requête Flex directement par le service Web Flex d'IBKR "
        "(lecture seule).",
    "Tax summary…": "Sommaire fiscal…",
    "One year's closed trades and retirement-plan contributions, gathered for tax season - to "
    "compare with your slips.":
        "Les transactions fermées et les cotisations de retraite d'une année, réunies pour la "
        "saison des impôts - à comparer avec vos feuillets.",
    "Breakdown by": "Répartition par", "Tag": "Étiquette", "Trades": "Transactions",
    "Win %": "Réussite %", "Total P&L": "Gain/perte total", "Avg R": "R moyen",
    "Click a column header to sort.": "Cliquez un en-tête de colonne pour trier.",
    # Coach
    "Your AI Trading Coach reviews your OWN past trades from the Journal and grades how well each "
    "was executed — risk defined, stop honored, reward vs risk, plan written down — not just "
    "whether it made money. Retrospective and educational: it reviews the past, it never tells you "
    "what to trade next.":
        "Votre coach de négociation revoit VOS transactions passées du Journal et note la qualité "
        "de leur exécution — risque défini, arrêt respecté, gain par rapport au risque, plan "
        "écrit — pas seulement si elles ont rapporté. Rétrospectif et éducatif : il revoit le "
        "passé et ne vous dit jamais quoi négocier ensuite.",
    "⚠ Process feedback, not financial advice. The Coach grades execution discipline from your "
    "journal; it does not predict prices or recommend trades. The AI chat uses your own Anthropic "
    "API key (per-use cost); with no key you still get the full offline rules-based review.":
        "⚠ Rétroaction sur la méthode, pas un conseil financier. Le Coach note la discipline "
        "d'exécution à partir de votre journal; il ne prédit pas les prix et ne recommande aucune "
        "transaction. Le clavardage IA utilise votre propre clé API Anthropic (coût par "
        "utilisation); sans clé, vous avez quand même la revue complète hors ligne.",
    "Anthropic API key (shared with AI Assist) — stored locally on this machine":
        "Clé API Anthropic (partagée avec l'Assistant IA) — gardée sur cet ordinateur",
    "Refresh from journal": "Actualiser à partir du journal",
    "Overall process grade:": "Note globale de la méthode :",
    "AI chat: off (no key) — offline review still available.":
        "Clavardage IA : désactivé (aucune clé) — la revue hors ligne reste disponible.",
    "Grade": "Note",
    "Each closed trade, graded on how it was executed. Click a row to see the grade breakdown below.":
        "Chaque transaction fermée, notée selon son exécution. Cliquez une ligne pour voir le "
        "détail de la note ci-dessous.",
    "Ask your coach — e.g. 'What's my biggest weakness?' or 'How's my stop discipline?'":
        "Demandez à votre coach — ex. « Quelle est ma plus grande faiblesse? » ou « Comment est ma "
        "discipline d'arrêt? »",
    "Ask coach": "Demander au coach", "Clear chat": "Effacer la conversation",
    # Backtest
    "Backtesting replays past prices and pretends to follow the strategy's buy/sell signals, to "
    "check whether it would have made money. Nothing here places real trades.":
        "Le test historique rejoue les prix passés en suivant les signaux d'achat et de vente de "
        "la stratégie, pour voir si elle aurait rapporté. Rien ici ne passe de vraies transactions.",
    "Splits the history into separate time periods and tests each one. This is the honesty check: a "
    "strategy that only worked in one lucky period is probably overfit. High consistency = "
    "trustworthy.":
        "Découpe l'historique en périodes distinctes et teste chacune. C'est le test "
        "d'honnêteté : une stratégie qui n'a fonctionné que dans une période chanceuse est "
        "probablement surajustée. Grande constance = fiable.",
    "Windows": "Fenêtres", "Run walk-forward": "Lancer le test progressif", "Window": "Fenêtre",
    "To": "À", "Win rate %": "Taux de réussite %", "Total return %": "Rendement total %",
    "Tries different values for ONE setting and ranks them best-first. The top row is the value "
    "that performed best — but a single standout spike is often luck; prefer a value whose "
    "neighbours also did well.":
        "Essaie différentes valeurs pour UN réglage et les classe de la meilleure à la pire. La "
        "première ligne a le mieux fait — mais un pic isolé est souvent de la chance; préférez une "
        "valeur dont les voisines ont aussi bien fait.",
    "Parameter": "Paramètre", "Values": "Valeurs", "Optimize": "Optimiser",
    "Tests the strategy on MANY stocks at once. If it only works on one lucky name it isn't "
    "reliable — look at the overall verdict to see if it works in general.":
        "Teste la stratégie sur PLUSIEURS titres à la fois. Si elle ne fonctionne que sur un nom "
        "chanceux, elle n'est pas fiable — regardez le verdict global pour voir si elle fonctionne "
        "en général.",
    "Symbols": "Symboles", "Run": "Lancer", "Profit factor": "Facteur de profit",
    "Max drawdown %": "Baisse maximale %",
    "Tests the strategy on ONE stock. The plain-English verdict below the table tells you if it "
    "would have made money and how bumpy the ride was.":
        "Teste la stratégie sur UN titre. Le verdict sous le tableau dit si elle aurait rapporté et "
        "à quel point le parcours aurait été cahoteux.",
    "Run backtest": "Lancer le test", "Metric": "Mesure", "Entry Date": "Date d'entrée",
    "Exit Date": "Date de sortie", "Return %": "Rendement %",
    "Research only — not financial advice.": "Recherche seulement — pas un conseil financier.",
    # Strategy builder
    "Build your own strategy with no code: pick conditions for when to BUY and when to SELL. Saved "
    "strategies appear in the Scanner and Backtest strategy dropdowns and run just like the "
    "built-in ones.":
        "Construisez votre propre stratégie sans code : choisissez les conditions d'ACHAT et de "
        "VENTE. Les stratégies enregistrées apparaissent dans les listes du Scanneur et du Test "
        "historique et fonctionnent comme celles intégrées.",
    "BUY when ALL of these are true:": "ACHETER quand TOUTES ces conditions sont vraies :",
    "+ Add condition": "+ Ajouter une condition",
    "SELL when ALL of these are true:": "VENDRE quand TOUTES ces conditions sont vraies :",
    "Plain-English preview:": "Aperçu en clair :",
    # Replay
    "Practice reading a chart with the future hidden. Load a symbol, pick where to start, then Play "
    "or step candle by candle. Indicators only use the revealed bars — no peeking ahead.":
        "Exercez-vous à lire un graphique sans voir la suite. Chargez un symbole, choisissez le "
        "départ, puis Lecture ou avancez chandelle par chandelle. Les indicateurs n'utilisent que "
        "les barres révélées — impossible de tricher.",
    "Start at bar": "Commencer à la barre",
    "How many bars to reveal before you start stepping.": "Combien de barres révéler avant de commencer.",
    "Load replay": "Charger la relecture", "Back to the start bar": "Retour à la barre de départ",
    "Step back one bar": "Reculer d'une barre", "▶ Play": "▶ Lecture",
    "Step forward one bar": "Avancer d'une barre", "Reveal all bars": "Révéler toutes les barres",
    "Speed": "Vitesse", "Load a symbol to begin.": "Chargez un symbole pour commencer.",
    # Seasonality
    "Seasonality: how a stock has behaved by calendar. Enter a symbol and the app measures the "
    "average return and win rate for each month and weekday over its history, and its year-by-year "
    "performance — so you can see whether the current month has tended to be kind or cruel to that "
    "name. Descriptive of the past, not a prediction of the future.":
        "Saisonnalité : comment un titre s'est comporté selon le calendrier. Inscrivez un symbole "
        "et l'application mesure le rendement moyen et le taux de réussite de chaque mois et jour "
        "de la semaine dans son historique, et sa performance année par année — pour voir si le "
        "mois en cours lui a été favorable ou non. Description du passé, pas une prévision.",
    "Enter a symbol and click Analyze.": "Inscrivez un symbole et cliquez Analyser.",
    "By month": "Par mois", "Avg %": "Moy. %", "Best %": "Meilleur %", "Worst %": "Pire %",
    "Years": "Années", "By weekday": "Par jour de la semaine", "Day": "Jour", "By year": "Par année",
    "Descriptive of past calendars only — not a forecast and not financial advice.":
        "Description des calendriers passés seulement — pas une prévision ni un conseil financier.",
    # Plugins, notes, links, help
    "Drop a .py file in the plugins/ folder that defines PLUGIN_NAME and compute(df) -> Series. It "
    "becomes usable as a field in Custom Filters and the Strategy Builder. See "
    "plugins/sample_hl_range.py for a template.":
        "Déposez dans le dossier plugins/ un fichier .py qui définit PLUGIN_NAME et compute(df) -> "
        "Series. Il devient un champ utilisable dans les filtres personnalisés et le constructeur "
        "de stratégies. Voyez plugins/sample_hl_range.py comme modèle.",
    "Reload plugins": "Recharger les modules",
    "A free-form scratchpad — your trading plan, ideas, reminders, rules. It saves automatically as "
    "you type (stored on this PC).":
        "Un bloc-notes libre — votre plan, vos idées, vos rappels, vos règles. Il s'enregistre "
        "automatiquement pendant que vous tapez (gardé sur cet ordinateur).",
    "Keep your go-to research sites, broker pages, news and screeners here. Enter a name and a URL "
    "(https:// is added if you omit it), then double-click a row to open it in your browser. Stored "
    "on your PC.":
        "Gardez ici vos sites de recherche, pages de courtier, nouvelles et filtres préférés. "
        "Inscrivez un nom et une adresse (https:// est ajouté s'il manque), puis double-cliquez "
        "une ligne pour l'ouvrir dans votre navigateur. Gardé sur votre ordinateur.",
    "Add / edit a link": "Ajouter / modifier un lien", "Name e.g. Finviz Map": "Nom ex. Carte Finviz",
    "URL": "Adresse", "URL e.g. finviz.com/map.ashx": "Adresse ex. finviz.com/map.ashx",
    "Group (optional)": "Groupe (facultatif)", "Open selected": "Ouvrir la sélection",
    "Import CSV": "Importer (CSV)", "Double-click a link to open it.": "Double-cliquez un lien pour l'ouvrir.",
    "📄  Open as PDF": "📄  Ouvrir en PDF",
    "Export the manual to a PDF and open it in your default viewer":
        "Exporter le manuel en PDF et l'ouvrir dans votre lecteur par défaut",
}
