#include "i18n.hpp"

#include <strings.h>

namespace dt {
namespace {
Lang g_lang = Lang::EN;

// clang-format off
const char *const T[(int)S::Count_][3] = {
    /* Subtitle */          {"Classroom Safety & Accountability Systems", "Systèmes de sécurité et de responsabilisation en classe", "Sistemas de seguridad y control en el aula"},
    /* Initializing */      {"Initializing…", "Initialisation…", "Iniciando…"},
    /* WelcomeTitle */      {"Welcome to DE-TECH-TIVE TECHNOLOGIES Inc", "Bienvenue chez DE-TECH-TIVE TECHNOLOGIES Inc", "Bienvenido a DE-TECH-TIVE TECHNOLOGIES Inc"},
    /* WelcomeBody */       {"Let's set up this classroom kiosk. You will choose a language, connect to Wi-Fi, then pair the kiosk with your school using an 8-character code.",
                             "Configurons cette borne de classe. Choisissez une langue, connectez-vous au Wi-Fi, puis associez la borne à votre école avec un code de 8 caractères.",
                             "Configuremos este quiosco del aula. Elija un idioma, conéctese al Wi-Fi y vincule el quiosco con su escuela usando un código de 8 caracteres."},
    /* GetStarted */        {"GET STARTED", "COMMENCER", "COMENZAR"},
    /* ChooseLanguage */    {"Choose your language", "Choisissez votre langue", "Elija su idioma"},
    /* WifiTitle */         {"Connect to Wi-Fi", "Connexion au Wi-Fi", "Conectar al Wi-Fi"},
    /* WifiScanning */      {"Scanning for networks…", "Recherche de réseaux…", "Buscando redes…"},
    /* WifiRescan */        {"Rescan", "Actualiser", "Buscar"},
    /* WifiHidden */        {"Hidden network…", "Réseau masqué…", "Red oculta…"},
    /* WifiPasswordFor */   {"Password for", "Mot de passe pour", "Contraseña para"},
    /* WifiPassword */      {"Password", "Mot de passe", "Contraseña"},
    /* WifiSsid */          {"Network name (SSID)", "Nom du réseau (SSID)", "Nombre de la red (SSID)"},
    /* WifiConnect */       {"CONNECT", "CONNECTER", "CONECTAR"},
    /* WifiConnecting */    {"Connecting…", "Connexion…", "Conectando…"},
    /* WifiConnectedTo */   {"Connected to", "Connecté à", "Conectado a"},
    /* WifiFailed */        {"Could not connect. Check the password and try again.", "Connexion impossible. Vérifiez le mot de passe.", "No se pudo conectar. Verifique la contraseña."},
    /* WifiNoNetworks */    {"No networks found", "Aucun réseau trouvé", "No se encontraron redes"},
    /* CheckingServer */    {"Checking school server…", "Vérification du serveur…", "Verificando el servidor…"},
    /* ServerOk */          {"School server reachable", "Serveur de l'école joignable", "Servidor escolar disponible"},
    /* ServerUnreachable */ {"School server unreachable — tap the gear to set the server address", "Serveur injoignable — touchez l'engrenage pour définir l'adresse", "Servidor inaccesible — toque el engranaje para definir la dirección"},
    /* Next */              {"NEXT", "SUIVANT", "SIGUIENTE"},
    /* Advanced */          {"Advanced settings", "Paramètres avancés", "Configuración avanzada"},
    /* HostUrl */           {"Host server URL", "URL du serveur", "URL del servidor"},
    /* Save */              {"SAVE", "ENREGISTRER", "GUARDAR"},
    /* Back */              {"BACK", "RETOUR", "ATRÁS"},
    /* Close */             {"CLOSE", "FERMER", "CERRAR"},
    /* PairTitle */         {"Pair this kiosk", "Associer cette borne", "Vincular este quiosco"},
    /* PairBody */          {"A school administrator enters this code in the DE-TECH-TIVE portal (Kiosks > Pair) or scans the QR code.",
                             "Un administrateur saisit ce code dans le portail DE-TECH-TIVE (Bornes > Associer) ou scanne le code QR.",
                             "Un administrador ingresa este código en el portal DE-TECH-TIVE (Quioscos > Vincular) o escanea el código QR."},
    /* PairWaiting */       {"Waiting for an administrator…", "En attente d'un administrateur…", "Esperando a un administrador…"},
    /* PairExpiresIn */     {"Code expires in", "Le code expire dans", "El código vence en"},
    /* PairError */         {"Cannot reach the school server. Retrying…", "Serveur injoignable. Nouvel essai…", "No se puede contactar al servidor. Reintentando…"},
    /* SignOut */           {"SIGN OUT", "SORTIE", "SALIDA"},
    /* SignIn */            {"SIGN IN", "ENTRÉE", "ENTRADA"},
    /* WhereGoing */        {"Where are you going?", "Où vas-tu ?", "¿A dónde vas?"},
    /* PresentCard */       {"Please present your student card in this frame", "Présente ta carte d'élève dans ce cadre", "Presenta tu credencial de estudiante en este recuadro"},
    /* Scanning */          {"Scanning…", "Lecture…", "Leyendo…"},
    /* HoldStill */         {"Hold the card still", "Ne bouge pas la carte", "Mantén la tarjeta quieta"},
    /* CameraMissing */     {"Camera not connected", "Caméra non connectée", "Cámara no conectada"},
    /* ServerOfflineScan */ {"Card reader offline — type your name instead", "Lecteur hors ligne — tape ton nom", "Lector sin conexión — escribe tu nombre"},
    /* TypeName */          {"Type my name", "Taper mon nom", "Escribir mi nombre"},
    /* FirstName */         {"First name", "Prénom", "Nombre"},
    /* LastName */          {"Last name", "Nom de famille", "Apellido"},
    /* Continue */          {"CONTINUE", "CONTINUER", "CONTINUAR"},
    /* SigningOutTo */      {"SIGNING OUT", "SORTIE", "SALIDA"},
    /* SigningInTo */       {"SIGNING IN", "ENTRÉE", "ENTRADA"},
    /* Room */              {"Room", "Salle", "Aula"},
    /* IsThisYourName */    {"Is this your name?", "Est-ce bien ton nom ?", "¿Es este tu nombre?"},
    /* Cancel */            {"CANCEL", "ANNULER", "CANCELAR"},
    /* Retake */            {"RETAKE", "REPRENDRE", "REPETIR"},
    /* Confirm */           {"CONFIRM", "CONFIRMER", "CONFIRMAR"},
    /* Saving */            {"Saving…", "Enregistrement…", "Guardando…"},
    /* SignedOutOk */       {"Signed out successfully", "Sortie enregistrée", "Salida registrada"},
    /* SignedInOk */        {"Signed in successfully", "Entrée enregistrée", "Entrada registrada"},
    /* At */                {"at", "à", "a las"},
    /* SavedOffline */      {"Saved on this kiosk — it will sync automatically", "Enregistré sur la borne — synchronisation automatique", "Guardado en el quiosco — se sincronizará automáticamente"},
    /* ErrorTryAgain */     {"Could not record this. Please try again.", "Impossible d'enregistrer. Réessaie.", "No se pudo registrar. Inténtalo de nuevo."},
    /* Lockdown */          {"LOCKDOWN — SIGN IN HERE  \xE2\x80\xA2", "CONFINEMENT — INSCRIS-TOI  \xE2\x80\xA2", "EMERGENCIA — REGÍSTRATE  \xE2\x80\xA2"},
    /* DiagTitle */         {"Kiosk diagnostics", "Diagnostic de la borne", "Diagnóstico del quiosco"},
    /* DiagIp */            {"IP address", "Adresse IP", "Dirección IP"},
    /* DiagRssi */          {"Wi-Fi signal", "Signal Wi-Fi", "Señal Wi-Fi"},
    /* DiagFw */            {"Firmware", "Micrologiciel", "Firmware"},
    /* DiagQueue */         {"Offline queue", "File hors ligne", "Cola sin conexión"},
    /* DiagHost */          {"School server", "Serveur", "Servidor"},
    /* DiagUid */           {"Device ID", "ID de l'appareil", "ID del dispositivo"},
    /* DiagCamera */        {"Camera", "Caméra", "Cámara"},
    /* Online */            {"online", "en ligne", "en línea"},
    /* Offline */           {"offline", "hors ligne", "sin conexión"},
    /* RePair */            {"RE-PAIR", "RÉASSOCIER", "REVINCULAR"},
    /* FactoryReset */      {"FACTORY RESET", "RÉINITIALISER", "RESTABLECER"},
    /* EnterPin */          {"Enter room admin PIN", "PIN administrateur", "PIN de administrador"},
    /* PinWrong */          {"Incorrect PIN", "PIN incorrect", "PIN incorrecto"},
    /* PinOffline */        {"Server offline: PIN cannot be verified", "Serveur hors ligne : PIN non vérifiable", "Servidor sin conexión: no se puede verificar el PIN"},
    /* DeviceRevoked */     {"This kiosk was unpaired by an administrator", "Cette borne a été dissociée par un administrateur", "Un administrador desvinculó este quiosco"},
    /* StartOver */         {"START OVER", "RECOMMENCER", "REINICIAR"},
    /* StartOverTitle */    {"Start setup over?", "Recommencer la configuration ?", "¿Reiniciar la configuración?"},
    /* StartOverBody */     {"This clears this kiosk's language, Wi-Fi and pairing, then restarts setup.",
                             "Cela efface la langue, le Wi-Fi et l'association de cette borne, puis relance la configuration.",
                             "Esto borra el idioma, el Wi-Fi y la vinculación de este quiosco, y reinicia la configuración."},
};
// clang-format on

struct DestTr {
    const char *en, *fr, *es;
};
const DestTr DEST[] = {
    {"Washroom", "Toilettes", "Baño"},     {"Office", "Bureau", "Oficina"},
    {"Library", "Bibliothèque", "Biblioteca"}, {"Guidance", "Orientation", "Orientación"},
    {"Water", "Eau", "Agua"},               {"Other", "Autre", "Otro"},
};
}  // namespace

void setLang(Lang l) { g_lang = l; }
void setLangCode(const std::string &code)
{
    g_lang = code == "fr" ? Lang::FR : code == "es" ? Lang::ES : Lang::EN;
}
Lang lang() { return g_lang; }
const char *langCode() { return g_lang == Lang::FR ? "fr" : g_lang == Lang::ES ? "es" : "en"; }
const char *tr(S key) { return T[(int)key][(int)g_lang]; }

std::string trDestination(const std::string &name)
{
    for (const auto &d : DEST) {
        if (strcasecmp(d.en, name.c_str()) == 0) return g_lang == Lang::FR ? d.fr : g_lang == Lang::ES ? d.es : d.en;
    }
    return name;
}

}  // namespace dt
