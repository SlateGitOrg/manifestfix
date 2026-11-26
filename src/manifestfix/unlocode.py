"""A bundled subset of UN/LOCODE: major container ports used to validate port fields.

The list is intentionally small (about 150 ports). A code outside it is reported as
`UNLOCODE_UNKNOWN` for review; it is not proof the code does not exist.
"""

from __future__ import annotations

_PORTS = """
CNSHA Shanghai|CNNGB Ningbo|CNSZX Shenzhen|CNYTN Yantian|CNTAO Qingdao|CNTSN Tianjin
CNXMN Xiamen|CNCAN Guangzhou|CNNSA Nansha|CNDLC Dalian|HKHKG Hong Kong|KRPUS Busan
KRINC Incheon|SGSIN Singapore|MYPKG Port Klang|MYTPP Tanjung Pelepas|THLCH Laem Chabang
VNSGN Ho Chi Minh City|VNHPH Haiphong|IDJKT Jakarta|IDSUB Surabaya|PHMNL Manila
LKCMB Colombo|INNSA Nhava Sheva|INMUN Mundra|INMAA Chennai|INCCU Kolkata|PKKHI Karachi
BDCGP Chittagong|AEJEA Jebel Ali|OMSLL Salalah|SAJED Jeddah|SADMM Dammam|JOAQJ Aqaba
EGPSD Port Said|EGALY Alexandria|ILHFA Haifa|ILASH Ashdod|TRMER Mersin|TRIST Istanbul
TRAMB Ambarli|TRIZM Izmir|GRPIR Piraeus|ESVLC Valencia|ESBCN Barcelona|ESALG Algeciras
ESBIO Bilbao|ITGOA Genoa|ITSPE La Spezia|ITGIT Gioia Tauro|ITTRS Trieste|ITVCE Venice
ITNAP Naples|ITLIV Livorno|FRMRS Marseille|FRLEH Le Havre|BEANR Antwerp|BEZEE Zeebrugge
NLRTM Rotterdam|DEHAM Hamburg|DEBRV Bremerhaven|GBFXT Felixstowe|GBSOU Southampton
GBLGP London Gateway|GBLIV Liverpool|IEDUB Dublin|SEGOT Gothenburg|PLGDN Gdansk
PLGDY Gdynia|LTKLJ Klaipeda|FIHEL Helsinki|NOOSL Oslo|NOBGO Bergen|DKCPH Copenhagen
DKAAR Aarhus|EETLL Tallinn|LVRIX Riga|PTLIS Lisbon|PTSIN Sines|PTLEI Leixoes
ROCND Constanta|BGVAR Varna|SIKOP Koper|HRRJK Rijeka|MAPTM Tanger Med|MACAS Casablanca
ZADUR Durban|ZACPT Cape Town|KEMBA Mombasa|TZDAR Dar es Salaam|NGLOS Lagos|GHTEM Tema
CIABJ Abidjan|SNDKR Dakar|AOLAD Luanda|USLAX Los Angeles|USLGB Long Beach|USOAK Oakland
USSEA Seattle|USTIW Tacoma|USHOU Houston|USNYC New York|USSAV Savannah|USCHS Charleston
USORF Norfolk|USMIA Miami|USBAL Baltimore|USJAX Jacksonville|USMSY New Orleans
CAVAN Vancouver|CAPRR Prince Rupert|CAMTR Montreal|CAHAL Halifax|MXZLO Manzanillo
MXLZC Lazaro Cardenas|MXVER Veracruz|PAONX Colon|PABLB Balboa|COCTG Cartagena
COBUN Buenaventura|ECGYE Guayaquil|PECLL Callao|CLVAP Valparaiso|CLSAI San Antonio
ARBUE Buenos Aires|BRSSZ Santos|BRPNG Paranagua|BRITJ Itajai|BRRIO Rio de Janeiro
UYMVD Montevideo|JMKIN Kingston|DOCAU Caucedo|JPTYO Tokyo|JPYOK Yokohama|JPNGO Nagoya
JPOSA Osaka|JPUKB Kobe|TWKHH Kaohsiung|TWKEL Keelung|TWTXG Taichung|AUMEL Melbourne
AUSYD Sydney|AUBNE Brisbane|AUFRE Fremantle|NZAKL Auckland|NZTRG Tauranga
"""

UNLOCODES: dict[str, str] = {
    entry.split(" ", 1)[0]: entry.split(" ", 1)[1]
    for entry in (e.strip() for e in _PORTS.replace("\n", "|").split("|"))
    if entry
}


def is_known(code: str) -> bool:
    return code in UNLOCODES


def port_name(code: str) -> str:
    return UNLOCODES[code]
