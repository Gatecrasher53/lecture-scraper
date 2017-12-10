# lecture-scraper
Scrapes university recordings page for lecture files and metadata.

Generates JSON object with the following format:

    JSON Register Data Structure
    
      [
      
          {
          
              courseName
              
              courseCode
              
              numOfLectures
              
              courselectures[
              
                  {
                  
                      'presenter'
                      
                      'date'
                      
                      'time'
                      
                      'length'
                      
                      'link'
                      
                      'notes'
                      
                  }
                  
              ]
              
          }
          
      ]

