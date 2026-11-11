// Desk Pet body: ultrasonic sensor in, LEDs + buzzer out.
// Wiring (HC-SR04): VCC->5V, GND->GND, TRIG->D9, ECHO->D10
// LEDs (each with a 220 ohm resistor to GND): RED->D3, YELLOW->D4, GREEN->D5
// Buzzer: D8 -> buzzer -> GND

const int trigPin = 9, echoPin = 10;
const int redPin = 4, yellowPin = 5, greenPin = 6, buzzer = 8; 

const float POKE_CM = 5.0f; // interacting with the robot
const float Near_CM = 50.0f; // The person is close to the robot
Uint8_t stable = 0;

//Gone means when a person is away from the robot
String lastzone = "GONE"; 
String candidate = "ZONE"; 

unsigned long duration; 
float distance;

float readDistance(){
  digitalWrite(trigPin, LOW); //Sending sounds
  delayMicroseconds(2);
  
  digitalWrite(trigPin, HIGH); //Receiving the sounds
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW); 

  //Wait up to 45 milliseconds to increase the accuracy.  
  duration = pulseIn(echoPin, HIGH, 45000UL);
  //Checking condition

  return distance = duration * 0.034 / 2; //speed of sound is 0.034 cm/microseconds / (time travel and bound back)
}

void testFuction(bool r, bool g, bool y){
  digitalWrite(redPin, r);
  digitalWrite(greenPin, g);
  digitalWrite(yellowPin, y);
  tone(buzzer, 3000); //send 1KHz sound signal...
  delay(500); //delay for 5 seconds
  noTone(buzzer); //Stop sounds
  delay(500); 
}

void show(String mood){
  if(mood == "HAPPY"){
    return "";
  }
  return "";
}

//Function that check the distance between a person and the robot
String stage(float d){
  //If the dis
  if(d < 0.0f){
    return "ERROR";
  }
  if(d <= POKE_CM && d > 0.0f){
    return "INTERACTING";
  }
  if(d > POKE_CM && d <= NEAR_CM){
    return "NEAR";
  }
  return "GONE";
}

void setup(){
  pinMode(trigPin, OUTPUT);
  pinMode(echoPin, INPUT);
  pinMode(redPin, OUTPUT);
  pinMode(greenPin, OUTPUT);
  pinMode(yellowPin, OUTPUT);
  pindMode(buzzer, OUTPUT);
  Serial.begin(9600);
  //Quick test
  testFunction(1,1,1);
  delay(500);
  testFunction(0,0,0);
}

void loop(){
  //Zone changes (needs at least 4 indentical to reduce hallucinations)
  String currentStage = stage(readDistance()); 
  if(currentStage == "Error"){
    Serial.println("critical ERROR: system required maintained!");
  }
  if(curentStage == candiate){
    if(stable < 4){
      stable++;
    }
  }
  else{
    candiate = currentStage; 
    stable = 1;
  }
  if(candiate != lastZone && stable >= 4){
    lastZone = candiate;
    Serial.println(lastZone);
  }

  //Communicate with Rasberry PI 
  //Read and excute from the serial port
  if(Serial.available() > 0){
    //Read the serial buffer until it reaches the end of the line
    String mood = Serial.readStringUntil('\n');
    //Removed white space
    mood.trim();
    show(mood);
  }
  delay(300);
}



