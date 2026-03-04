#include <SPI.h>
#include <Ethernet.h>
#include <EthernetUDP.h>
#include <Dynamixel2Arduino.h>

// ---------- Настройки устройства ----------
#define I_AM_MANIPULATOR      // РАСКОММЕНТИРОВАТЬ для манипулятора, ЗАКОММЕНТИРОВАТЬ для лампы

const int TABLE_NUM = 3;      
const int DEVICE_NUM = 1;
const int LAST_MAC = 1;     

// Глобальные флаги типа устройства
bool is_lamp = false;
bool is_manip = false;

// Пины светодиодов
const int PIN_Y = 2;
const int PIN_G = 3;
const int PIN_B = 4;
const int PIN_R = 5;

// Сетевые настройки
byte mac[] = { 0xDE, 0xAD, 0xBE, 0xEF, 0xFE, 0x00 };
IPAddress server(192, 168, 0, 100);
const unsigned int SERVER_PORT = 8888;
const unsigned int LOCAL_PORT = 8889;

EthernetUDP Udp;
char device_id[25]; 

// Настройки Dynamixel
#define DXL_SERIAL Serial3
#define DXL_DIR_PIN -1
const uint8_t NUM_MOTORS = 6; 
const uint8_t MOTOR_IDS[NUM_MOTORS] = {1, 2, 3, 4, 5, 6}; 
const uint32_t DXL_BAUDRATE = 1000000;

Dynamixel2Arduino dxl(DXL_SERIAL, DXL_DIR_PIN);

// Таймеры
unsigned long lastStatus = 0;
const unsigned long STATUS_INTERVAL = 5000; 
unsigned long lastReg = 0;
const unsigned long REG_INTERVAL = 30000;

// ---------- Прототипы функций ----------
void sendRegistration();
void sendFullStatus();
void initMotors();
void setMotorPosition(uint8_t id, uint16_t pos);
void setColor(char color, int state);
void allLeds(int state);

void setup() {
  pinMode(PIN_R, OUTPUT); pinMode(PIN_Y, OUTPUT);
  pinMode(PIN_G, OUTPUT); pinMode(PIN_B, OUTPUT);

  Serial.begin(9600);

  // Формируем идентификатор в зависимости от типа
  #ifdef I_AM_MANIPULATOR
    sprintf(device_id, "ID:T%d:MP:N%d", TABLE_NUM, DEVICE_NUM);
  #else
    sprintf(device_id, "ID:T%d:DL:N%d", TABLE_NUM, DEVICE_NUM);
  #endif

  String idStr = String(device_id);
  is_lamp = idStr.indexOf(":DL:") > 0;
  is_manip = idStr.indexOf(":MP:") > 0;

  // Уникальный MAC: для ламп 1-8, для пультов было 9-12. Конфликта нет.
  mac[5] = LAST_MAC;

  Ethernet.begin(mac);
  delay(1000);
  Udp.begin(LOCAL_PORT);

  if (is_manip) {
    initMotors();
  }

  sendRegistration();
  lastReg = millis();
  Serial.print("Started as: "); Serial.println(device_id);
}

void loop() {
  int packetSize = Udp.parsePacket();
  if (packetSize) {
    char buf[64];
    int len = Udp.read(buf, sizeof(buf) - 1);
    if (len > 0) {
      buf[len] = '\0';
      String cmd = String(buf); 
      cmd.trim();

      if (is_lamp) {
        if (cmd.length() == 2) {
          setColor(cmd.charAt(0), cmd.substring(1).toInt());
        } else if (cmd == "1111") {
          allLeds(HIGH);
        } else if (cmd == "0000") {
          allLeds(LOW);
        }
      } 
      
      if (is_manip) {
        if (cmd.startsWith("M")) {
          int colon = cmd.indexOf(':');
          if (colon > 1) {
            uint8_t id = cmd.substring(1, colon).toInt();
            uint16_t pos = cmd.substring(colon + 1).toInt();
            setMotorPosition(id, pos);
          }
        }
      }
    }
  }

  // Отправка статуса (для ламп — данные, для манипулятора — пинг)
  if (millis() - lastStatus >= STATUS_INTERVAL) {
    sendFullStatus();
    lastStatus = millis();
  }
  
  // Перерегистрация
  if (millis() - lastReg >= REG_INTERVAL) {
    sendRegistration();
    lastReg = millis();
  }
}

// ---------- Реализация функций ----------

void initMotors() {
  dxl.begin(DXL_BAUDRATE);
  dxl.setPortProtocolVersion(2.0);
  for (int i = 0; i < NUM_MOTORS; i++) {
    uint8_t id = MOTOR_IDS[i];
    if (dxl.ping(id)) {
      dxl.torqueOn(id);
      dxl.setOperatingMode(id, OP_POSITION);
      dxl.setGoalPosition(id, 2048, UNIT_RAW);
      Serial.print("Motor "); Serial.print(id); Serial.println(" OK");
    }
  }
}

void setMotorPosition(uint8_t id, uint16_t pos) {
  if (id < 1 || id > NUM_MOTORS) return;
  pos = constrain(pos, 0, 4095);
  dxl.setGoalPosition(MOTOR_IDS[id - 1], pos, UNIT_RAW);
}

void setColor(char color, int state) {
  int pin = -1;
  if (color == 'R') pin = PIN_R;
  else if (color == 'Y') pin = PIN_Y;
  else if (color == 'G') pin = PIN_G;
  else if (color == 'B') pin = PIN_B;
  if (pin != -1) digitalWrite(pin, state ? HIGH : LOW);
}

void allLeds(int state) {
  digitalWrite(PIN_R, state); digitalWrite(PIN_Y, state);
  digitalWrite(PIN_G, state); digitalWrite(PIN_B, state);
}

void sendRegistration() {
  Udp.beginPacket(server, SERVER_PORT);
  Udp.write(device_id); // Теперь переменная в правильном регистре
  Udp.endPacket();
}

void sendFullStatus() {
  Udp.beginPacket(server, SERVER_PORT);
  if (is_lamp) {
    String s = "T" + String(TABLE_NUM) + ":DL:N" + String(DEVICE_NUM) +
               ":R" + String(digitalRead(PIN_R)) + ":Y" + String(digitalRead(PIN_Y)) +
               ":G" + String(digitalRead(PIN_G)) + ":B" + String(digitalRead(PIN_B));
    Udp.write(s.c_str());
  } else {
    // Для манипулятора просто шлем ID как пинг, чтобы сервер не удалил из списка
    Udp.write(device_id);
  }
  Udp.endPacket();
}