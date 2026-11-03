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
}
