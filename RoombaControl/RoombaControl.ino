// Desk Pet body: ultrasonic sensor in, LEDs + buzzer out.
// Wiring (HC-SR04): VCC->5V, GND->GND, TRIG->D9, ECHO->D10
// LEDs (each with a 220 ohm resistor to GND): RED->D3, YELLOW->D4, GREEN->D5
// Buzzer: D8 -> buzzer -> GND

const int trigPin = 9, echoPin = 10;
const int redPin = 4, yellowPin = 5, greenPin = 6, buzzer = 8; 

const float POKE_CM = 5.0f; // interacting with the robot
const float NEAR_CM = 50.0f; // The person is close to the robot
uint8_t stable = 0;

//Gone means when a person is away from the robot
String lastZone = "GONE"; 
String candidate = "ZONE"; 

unsigned long duration; 

float readDistance(){
  digitalWrite(trigPin, LOW); //Sending sounds
  delayMicroseconds(2);
  
  digitalWrite(trigPin, HIGH); //Receiving the sounds
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW); 

  //Wait up to 45 milliseconds to increase the accuracy.  
  duration = pulseIn(echoPin, HIGH, 45000UL);
  //Checking condition
  if(duration == 0.0f){
    return -1.0f;
  }

  return duration * 0.034 / 2; //speed of sound is 0.034 cm/microseconds / (time travel and bound back)
}

void led(bool r, bool g, bool y){
  digitalWrite(redPin, r);
  digitalWrite(greenPin, g);
  digitalWrite(yellowPin, y);
  // tone(buzzer, 3000, 300); //send 1KHz sound signal...
  // delay(500); //delay for 5 seconds
  // noTone(buzzer); //Stop sounds
  // delay(500); 
}

void show(String mood){
  //Making a happy sounds by quick wave sound
  if(mood == "HAPPY"){
    led(0,1,0);
    tone(buzzer, 2000, 250);
    delay(150);
    tone(buzzer, 850, 200);
    delay(230);
    tone(buzzer, 450, 100);
    delay(220);
  }
  else if(mood == "GRUMPY"){
    led(0,0,1);
    tone(buzzer, 800, 100);
    delay(200);
    tone(buzzer, 2500, 400);
    delay(350);
    tone(buzzer, 560, 250);
    delay(250);
  }
  else if(mood == "ANGRY"){
    led(1,0,0);
    for(int i = 0; i < 10; i++){
      tone(buzzer, 2400, 60);
      delay(150);
    }
  }
  else if (mood == "SAD") {
    led(0, 0, 0);
    tone(buzzer, 500, 300); delay(350);
    tone(buzzer, 400, 300); delay(350);
    tone(buzzer, 300, 500); delay(550);
    digitalWrite(yellowPin, HIGH);  // dim "sulking" light
  }
}

//Function that check the distance between a person and the robot
String stage(float d){
  //If the dis
  if(d == -1.0f){
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
  pinMode(buzzer, OUTPUT);
  Serial.begin(9600);
  //Quick test
  // testFunction(1,1,1);
  // delay(500);
  // testFunction(0,0,0);
}

void loop(){
  float distance = readDistance();
  if(distance < 0.0f){
    delay(300);
    return;
  }
  //Zone changes (needs at least 4 indentical to reduce hallucinations)
  String currentStage = stage(distance);

  if(currentStage == "ERROR"){
    Serial.println("critical ERROR: system required maintained!");
  }
  if(currentStage == candidate){
    if(stable < 4){
      stable++;
    }
  }
  else{
    candidate = currentStage; 
    stable = 1;
  }
  if(candidate != lastZone && stable >= 4){
    lastZone = candidate;
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



