// Kiosk UI strings in English, Français and Español (UTF-8; Latin-1 glyphs are compiled into dt_font_*).
#pragma once
#include <string>

namespace dt {

enum class Lang { EN = 0, FR = 1, ES = 2 };

enum class S {
    Subtitle, Initializing,
    WelcomeTitle, WelcomeBody, GetStarted,
    ChooseLanguage,
    WifiTitle, WifiScanning, WifiRescan, WifiHidden, WifiPasswordFor, WifiPassword, WifiSsid, WifiConnect,
    WifiConnecting, WifiConnectedTo, WifiFailed, WifiNoNetworks, CheckingServer, ServerOk, ServerUnreachable,
    Next, Advanced, HostUrl, Save, Back, Close,
    PairTitle, PairBody, PairWaiting, PairExpiresIn, PairError,
    SignOut, SignIn, WhereGoing,
    PresentCard, Scanning, HoldStill, CameraMissing, ServerOfflineScan, TypeName, FirstName, LastName, Continue,
    SigningOutTo, SigningInTo, Room, IsThisYourName, Cancel, Retake, Confirm, Saving,
    SignedOutOk, SignedInOk, At, SavedOffline, ErrorTryAgain,
    Lockdown,
    DiagTitle, DiagIp, DiagRssi, DiagFw, DiagQueue, DiagHost, DiagUid, DiagCamera, Online, Offline,
    RePair, FactoryReset, EnterPin, PinWrong, PinOffline, DeviceRevoked,
    StartOver, StartOverTitle, StartOverBody,
    Count_
};

void setLang(Lang l);
void setLangCode(const std::string &code);
Lang lang();
const char *langCode();
const char *tr(S key);
/** Translates the six default destination names; custom school destinations are shown as configured. */
std::string trDestination(const std::string &name);

}  // namespace dt
