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
}
